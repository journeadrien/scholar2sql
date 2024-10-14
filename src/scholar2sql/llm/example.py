from pydantic import BaseModel
import json
from typing import Dict, List, Any

class Example(BaseModel):
    """
    A class representing an example with inputs, sections, outputs, and mock data.

    Attributes:
        input_parameters (Dict[str, Any]): Input data for the example.
        sections (List[str]): List of sections in the example.
        output_features (Dict[str, Any]): Output data for the example.
        _mock (Dict[str, str]): Cached mock data (private attribute).
    """

    input_parameters: Dict[str, Any]
    sections: Dict[str, Any]
    output_features: Dict[str, Any]
    mock: Dict[str, str] = {}

    def get_mock(self, research_question: str, mapping: BaseModel) -> Dict[str, str]:
        """
        Generate and return mock data for the example.

        Args:
            question (str): Template string for the question.
            output_model (BaseModel): Pydantic model for formatting the output.

        Returns:
            Dict[str, str]: Mock data including question, sections, and answer.
        """
        if not self.mock:
            self.mock = {
                "research_question": research_question.format(**self.input_parameters),
                "sections": self._escape_braces(json.dumps(self.sections)),
                "answer": self._escape_braces(mapping(**self.output_features).model_dump_json())
            }
        return self.mock

    @staticmethod
    def _escape_braces(s: str) -> str:
        """
        Escape curly braces in a string by doubling them.
        """
        return s.replace("{", "{{").replace("}", "}}")