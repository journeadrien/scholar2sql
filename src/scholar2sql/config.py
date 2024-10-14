import yaml
from pathlib import Path
import os
from pydantic import BaseModel, ConfigDict, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, YamlConfigSettingsSource, PydanticBaseSettingsSource
from typing import Literal, Optional, Type, Tuple
from .scholar import Scholar
from .sql import SqlAPIWrapper
from .metadata import Metadata
from .schema import SchemaInputParameter
import json
import itertools
import asyncio
import logging
from functools import cached_property
from .llm import ScientificPaperPrompt, OpenAiAPIWrapper
from typing_extensions import Self
from scholaretl.article import Article

from rich.logging import RichHandler
from rich.console import Console
from rich.theme import Theme

console = Console(theme=Theme({"logging.level.custom": "green"}))

logger = logging.getLogger(__name__)

class ConfigsLogging(BaseModel):
    """Logging config."""
    
    level: Literal["debug", "info", "warning", "error", "critical"]
    external_packages: Literal["debug", "info", "warning", "error", "critical"] = "warning"
    _log_format: str = " [%(name)s.%(funcName)s()] %(message)s"
    _log_datefmt: str = "%H:%M:%S"

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def set_logging_levels(self):
        """Set the logging levels for the application and external packages."""
        logging.getLogger().setLevel(self.external_packages.upper())
        logging.getLogger("scholar2sql").setLevel(self.level.upper())
        logging.basicConfig(
            format=self._log_format,
            datefmt=self._log_datefmt,
            handlers=[RichHandler(rich_tracebacks=True, tracebacks_show_locals=True, console=console)],)
        return self
    
class DataProcessing(BaseModel):
    """Processing Config"""
    overwrite_existing: bool = False

class Configs(BaseSettings):
    """All configurations for the application."""

    sql_database: SqlAPIWrapper
    logging: ConfigsLogging
    scholar_search: Scholar
    prompt: ScientificPaperPrompt
    openai: OpenAiAPIWrapper
    data_processing: DataProcessing

    overwrite: bool = False

    @classmethod
    def from_yaml(cls, path: Path):
        """Load configurations from a YAML file."""
        with open(path, 'r') as yaml_file:
            dx = yaml.safe_load(yaml_file) or {}
        return cls(**dx)

    @model_validator(mode='after')
    def configure_components(self) -> Self:
        """Configure the components of the application."""
        self.openai._chain = self.prompt.prompt | self.openai.llm | self.prompt.parser
        self.sql_database._input_parameters = self.prompt.input_parameters
        self.sql_database._output_features = self.prompt.output_features
        return self

    async def extract_and_fill_sql(self, research_question: str, article: Article, inputs_values: tuple[SchemaInputParameter], metadata: Metadata) -> bool:
        """
        Extract and fill SQL records for a given article and question.

        Args:
            research_question (str): The question to be answered.
            article (Article): The article to extract information from.
            inputs_values (tuple[SchemaInputParameter]): The input values for the SQL schema.
            metadata (Metadata): The metadata for the article.

        Returns:
            bool: True if the record was successfully inserted or updated in the SQL database, False otherwise.
        """
        coroutine_top_k_docs = asyncio.to_thread(self.scholar_search.get_top_sections, article=article, research_question=research_question)
        coroutine_record_id = self.sql_database.find_record(inputs_values=inputs_values, pubmed_id=metadata.pubmed_id.value)

        sections, record_id = await asyncio.gather(coroutine_top_k_docs, coroutine_record_id)

        metadata.sections.value = sections

        if self.data_processing.overwrite_existing or record_id is None:
            outputs = await self.openai.invoke_llm(research_question=research_question, sections=sections, pubmed_id=metadata.pubmed_id.value)
            if outputs is not None:  # In case of parsing error
                await self.sql_database.upsert_record(record_id=record_id, inputs_values=inputs_values, metadata=metadata, outputs=outputs)
                return True
            return False
        logger.debug(f"Record already in SQL at id: {record_id} for pubmed_id {metadata.pubmed_id.value}")
        return False

    async def run(self):
        """Run the application and extract features from articles."""
        await self.sql_database.create_table()
        tasks = []
        for research_question, pubmed_query, inputs_values in self.prompt.iter():
            async for article, metadata in self.scholar_search.iter(pubmed_query):
                tasks.append(asyncio.ensure_future(self.extract_and_fill_sql(research_question=research_question, article=article, inputs_values=inputs_values, metadata=metadata)))
        results = await asyncio.gather(*tasks)

        logger.info(f"Finished extracting features of {len(tasks)} articles and adding {sum(results)} articles at a cost of {self.openai._total_cost}")