from enum import Enum
from typing import List, Dict, Union, Optional, Type
from pydantic import BaseModel, computed_field, model_validator, field_validator
from pydantic.json_schema import GetJsonSchemaHandler
from pydantic_core import core_schema
import json

class EnumSchemaDoc(Enum):
    """
    Enumeration class with added documentation support for JSON schema.
    """
    def __init__(self, value, description):
        self._value_ = value
        self.description = description

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler):
        schema = handler(core_schema)
        schema['documentation'] = {e.value: e.description for e in cls}
        return schema

class SchemaEnum(BaseModel):
    """
    Represents a choice in a schema with name, alias, and description.
    """
    name: str
    alias: str
    description: str = ""

class SchemaItem(BaseModel):
    """
    Represents an item in the schema with name and optional aliases.
    """
    name: str
    llm_alias: Optional[List[str]] = None
    pubmed_alias: Optional[List[str]] = None

    @field_validator("pubmed_alias", "llm_alias", mode="before")
    def parse_aliases(cls, value: Optional[str]) -> Optional[List[str]]:
        """Parse JSON string to list of aliases if provided."""
        return json.loads(value) if value else None

class SchemaMetadata(BaseModel):
    """
    Base class for schema metadata with data_type inference and SQL data_type mapping.
    """
    name: str
    data_type: Type
    max_length: Optional[int] = None
    value: Optional[Union[str, List, Dict]] = None

    @computed_field
    @property
    def sql_data_type(self) -> str:
        """Infer SQL data_type based on the Python data_type and max_length."""
        if self.data_type in (list, dict) or getattr(self, 'multiple_values', False):
            return "JSON"
        if issubclass(self.data_type, EnumSchemaDoc) or self.data_type == str:
            if self.max_length is None or self.max_length > 255:
                return "LONGTEXT"
            if self.max_length < 30:
                return f"VARCHAR({self.max_length})"
            return "TINYTEXT"
        if self.data_type == bool:
            return "BOOL"
        if self.data_type == int:
            return "INT"
        if self.data_type == float:
            return "FLOAT"
        raise ValueError(f"Invalid data_type {self.data_type} for {self.name}. Choose from [dict, list, str, bool, int, float]")

    @model_validator(mode="before")
    def process_data_type_and_choices(cls, values: Dict) -> Dict:
        """Process data_type and choices, creating Enum if necessary."""
        if "allowed_values" in values:
            enum_name = f'Enum{values["name"]}'
            enum_members = {choice['name']: (choice['alias'], choice['description']) for choice in values["allowed_values"]}
            values["data_type"] = EnumSchemaDoc(enum_name, enum_members)
        
        data_type_mapping = {
            "str": str, "int": int, "float": float, "bool": bool,
            "list": list, "dict": dict
        }
        values["data_type"] = data_type_mapping.get(values.get("data_type", "str"), values.get("data_type", str))
        return values

class SchemaInputParameter(SchemaMetadata):
    """
    Represents input schema with a list of SchemaItems.
    """
    value: List[SchemaItem]

class SchemaOutputFeature(SchemaMetadata):
    """
    Represents output schema with additional properties.
    """
    description: str = ""
    required: bool = True
    multiple_values: bool = False # Corrected typo
    allowed_values: Optional[List[SchemaEnum]] = None