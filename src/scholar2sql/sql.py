from pydantic import BaseModel, SecretStr, ConfigDict
import os
import json
import asyncio
from mysql.connector.aio import connect
import logging
from .schema import SchemaInputParameter, SchemaOutputFeature, SchemaItem, EnumSchemaDoc
from .metadata import Metadata
from functools import cached_property

logger = logging.getLogger(__name__)

class SqlAPIWrapper(BaseModel):
    """
    Manages database operations for a specific table.

    This class handles connection to a MySQL database, table creation,
    data insertion, and updates.

    Attributes:
        host (str): Database host address.
        username (str): Database username.
        password (SecretStr): Database password.
        database (str): Database name.
        table (str): Table name for operations.
        metadata (Metadata): Metadata for the table.
    """

    host: str
    username: str = None
    password: SecretStr = None
    database: str = None
    table: str

    metadata: Metadata = Metadata()
    _input_parameters: list[SchemaInputParameter] = []
    _output_features: list[SchemaOutputFeature] = []

    _semaphore: asyncio.Semaphore = asyncio.Semaphore(5)

    def get_connection(self):
        """
        Establishes and returns a database connection.

        Returns:
            mysql.connector.aio.Connection: Asynchronous database connection.
        """
        return connect(
            host=self.host,
            user=self.username,
            password=self.password.get_secret_value(),
            database=self.database
        )
    
    async def create_table(self):
        """Creates the table if it doesn't exist."""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table} (
            id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            {','.join([f"{key} {value['sql_data_type']}" for key, value in self.metadata.model_dump(include=self.metadata.to_save).items()])},
            {','.join([f"{item.name} {item.sql_data_type}" for item in self._input_parameters])},
            {', '.join([f"{item.name} {item.sql_data_type}" for item in self._output_features])}
        );
        """
        try:
            async with self._semaphore, await self.get_connection() as conn:
                async with await conn.cursor() as cursor:
                    await cursor.execute(create_table_query)
                logger.info(f"Create table {self.table}")
        except Exception as e:
            logger.error(f"Error creating table: {e}")

    async def drop_table(self):
        """Drops the table if it exists."""
        drop_table_query = f"DROP TABLE IF EXISTS {self.table}"
        try:
            async with self._semaphore, await self.get_connection() as conn:
                async with await conn.cursor() as cursor:
                    await cursor.execute(drop_table_query)
                logger.info(f"Table {self.table} dropped successfully")
        except Exception as e:
            logger.error(f"Error dropping table: {e}")

    @cached_property
    def input_columns(self) -> list:
        """Returns a list of input column names."""
        return [item.name for item in self._input_parameters]
    
    @cached_property
    def metadata_columns(self) -> list:
        """Returns a list of metadata column names."""
        return [key for key in self.metadata.model_dump(include=self.metadata.to_save)]

    @cached_property
    def all_columns(self) -> list:
        """Returns a list of all column names."""
        return self.metadata_columns + self.input_columns + [item.name for item in self._output_features]
    
    async def find_record(self, inputs_values: list[SchemaItem], pubmed_id: str) -> int | None:
        """
        Checks if a record exists based on input values and pubmed_id.

        Args:
            input_values (list): List of input values.
            pubmed_id (str): PubMed ID.

        Returns:
            int or None: Record ID if found, None otherwise.
        """
        conditions = ' AND '.join(
            [f"{col}='{val.name}'" for col, val in zip(self.input_columns, inputs_values)]
        ) + f" AND pubmed_id='{pubmed_id}'"

        query = f"SELECT id FROM {self.table} WHERE {conditions};"
        
        async with self._semaphore, await self.get_connection() as conn:
            async with await conn.cursor() as cursor:
                await cursor.execute(query)
                result = await cursor.fetchone()
            
        return result[0] if result else None

    async def upsert_record(self, record_id: int, inputs_values: list[SchemaItem], metadata: Metadata, outputs):
        """
        Inserts a new record or updates an existing one.

        Args:
            record_id (int): ID of the existing record (None for new records).
            inputs_values (list[SchemaItem]): List of input values.
            metadata (Metadata): Record metadata.
            outputs: Output data.
        """
        if record_id is None:
            query = f"INSERT INTO {self.table} ({', '.join(self.all_columns)}) VALUES ({', '.join([f'%({col})s' for col in self.all_columns])});"
        else:
            query = f"UPDATE {self.table} SET {', '.join([f'{col} = %({col})s' for col in self.all_columns])} WHERE id = {record_id};"

        data = {
            **{
                key: json.dumps(value['value']) if isinstance(value['value'], (list, dict)) else value['value'] 
                for key, value in metadata.model_dump(include=self.metadata.to_save).items()
            },
            **{
                input_name: input_value.name for input_name, input_value in zip(self.input_columns, inputs_values)
            },
            **{
                key: json.dumps(value) if isinstance(value, (list, dict)) else value 
                for key, value in outputs.model_dump(mode='json').items()
            }
        }

        try:
            async with self._semaphore, await self.get_connection() as conn:
                async with await conn.cursor() as cursor:
                    await cursor.execute(query, data)
                await conn.commit()
            
            logger.debug(
                f"Successfully {'inserted' if record_id is None else 'updated'} record {cursor.lastrowid if record_id is None else record_id} with PubMed ID {metadata.pubmed_id.value}"
            )
        except Exception as e:
            logger.error(f"Error upserting record: {e}")