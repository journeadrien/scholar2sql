from pydantic import BaseModel, Field, computed_field, create_model, model_validator, ConfigDict
from functools import cached_property
import itertools
from typing import Iterator, Optional, List, Tuple
from langchain.output_parsers import PydanticOutputParser
from langchain.prompts.few_shot import FewShotPromptTemplate
from langchain.prompts.prompt import PromptTemplate

from .example import Example
from ..schema import SchemaInputParameter, SchemaOutputFeature

PROMPT_TEMPLATE = """Given the following extracted parts of a scientific paper. The goal is to generate a detailed summary in JSON format aiming {research_goal}.
Only respond when there is strong evidence that the paper reports thorough answer.{information_to_exclude}
For your reasoning and answering keep in mind that some sections may contain syntax errors (symbols, math equations, formulas, abbreviations, punctuation marks etc.)\n{format_instructions}"""

class ScientificPaperPrompt(BaseModel):
    """
    A class to generate and manage prompts for scientific paper analysis.
    """

    prompt_template: str = PROMPT_TEMPLATE
    research_question: str
    research_goal: str
    information_to_exclude: str = ""
    input_parameters: List[SchemaInputParameter]
    output_features: List[SchemaOutputFeature]
    examples: List[Example] = []

    @model_validator(mode='after')
    def generate_example_mocks(self) -> 'ScientificPaperPrompt':
        """Generate mock examples for each example in the prompt."""
        for example in self.examples:
            example.get_mock(research_question=self.research_question, mapping=self.mapping)
        return self

    @staticmethod
    def build_query(items: Tuple[SchemaInputParameter, ...]) -> str:
        """Build a query string from a tuple of SchemaInput items."""
        return " AND ".join(
            f"({' OR '.join([item.name] + (item.pubmed_alias or []))})"
            for item in items
        )

    @computed_field
    @cached_property
    def mapping(self) -> BaseModel:
        """Create dynamically a Pydantic model for the output mapping."""
        model_fields = {}
        for output in self.output_features:
            field_type = List[output.data_type] if output.multiple_values else output.data_type
            field = Field(description=output.description)
            if not output.required:
                field_type = Optional[field_type]
                field.default = None
            model_fields[output.name] = (field_type, field)

        return create_model('Mapping', **model_fields, __config__=ConfigDict(use_enum_values=True))

    @computed_field
    @cached_property
    def parser(self) -> PydanticOutputParser:
        """Create a PydanticOutputParser for the mapping."""
        return PydanticOutputParser(pydantic_object=self.mapping)

    @computed_field
    @cached_property
    def prompt(self) -> FewShotPromptTemplate:
        """Create a FewShotPromptTemplate for the prompt."""
        return FewShotPromptTemplate(
            examples=[example.mock for example in self.examples],
            example_prompt=PromptTemplate(
                input_variables=["research_question", "sections", "answer"],
                template="QUESTION: {research_question}\n{sections}\n{answer}"
            ),
            prefix=self.prompt_template,
            suffix="QUESTION: {research_question}\n{sections}\n",
            input_variables=["research_question", "sections"],
            partial_variables={
                "research_goal": self.research_goal,
                "information_to_exclude": self.information_to_exclude,
                "format_instructions": self.parser.get_format_instructions(),
            },
        )
    
    def format_question(self, items: Tuple[SchemaInputParameter, ...]) -> str:
        """Format the question with input items."""
        return self.research_question.format(**{
            self.input_parameters[i].name: f"{item.name} (a.k.a {', '.join(item.llm_alias)})" if item.llm_alias else item.name
            for i, item in enumerate(items)
        })

    def iter(self) -> Iterator[Tuple[str, str, Tuple[SchemaInputParameter, ...]]]:
        """Iterate over all combinations of inputs, yielding formatted questions and queries."""
        for input_parameter_product in itertools.product(*[item.value for item in self.input_parameters]):
            yield (
                self.format_question(input_parameter_product),
                self.build_query(input_parameter_product),
                input_parameter_product
            )