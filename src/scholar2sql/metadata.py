from pydantic import BaseModel, field_validator
from typing import Dict, List, Literal
from typing_extensions import Self
from .schema import SchemaMetadata

class Metadata(BaseModel):
    """
    A class representing metadata for PubMed articles.

    Attributes:
        pubmed_id (SchemaMetadata): Metadata for the PubMed ID.
        format (SchemaMetadata): Metadata for the article format.
        sections (SchemaMetadata): Metadata for article sections.
        to_save (List[str]): List of fields to save, always starting with 'pubmed_id'.

    Methods:
        update_from_dict: Updates metadata fields from a dictionary.
    """

    pubmed_id: SchemaMetadata = SchemaMetadata(
        name="pubmed_id",
        type="str",
        size=10
    )
    format: SchemaMetadata = SchemaMetadata(
        name="format",
        type="str",
        size=15
    )
    sections: SchemaMetadata = SchemaMetadata(
        name="sections",
        type="dict",
    )
    to_save: List[Literal["pubmed_id", "format", "sections"]] = ["pubmed_id", "format", "sections"]

    def update_from_dict(self, data: Dict[str, any]) -> Self:
        """
        Updates metadata fields from a dictionary.

        Args:
            data (Dict[str, any]): Dictionary containing metadata values.

        Returns:
            Self: Updated instance of the Metadata class.
        """
        for field in self.model_fields:
            if field in data and hasattr(self, field):
                setattr(getattr(self, field), 'value', data[field])
        return self

    @field_validator("to_save", mode="before")
    @classmethod
    def validate_to_save(cls, value: List[str]) -> List[str]:
        """
        Validates that 'pubmed_id' is the first field in the 'to_save' list.

        Args:
            value (List[str]): List of fields to save.

        Returns:
            List[str]: Validated list of fields to save.

        Raises:
            ValueError: If 'pubmed_id' is not the first field in the list.
        """
        if not value or value[0] != "pubmed_id":
            raise ValueError("'pubmed_id' must be the first metadata field in 'to_save'")
        return value