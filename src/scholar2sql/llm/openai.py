import asyncio
import logging
from functools import cached_property

from tenacity import retry, stop_after_attempt, retry_if_exception_type, wait_random
from langchain.chains import LLMChain
from langchain.callbacks.tracers import ConsoleCallbackHandler
from langchain_community.callbacks import get_openai_callback, OpenAICallbackHandler
from langchain_core.exceptions import OutputParserException
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr, computed_field
from typing import List
from openai import AuthenticationError
import httpx

logger = logging.getLogger(__name__)


class OpenAiAPIWrapper(BaseModel):
    """
    Wrapper for OpenAI API calls, managing rate limits and providing logging.

    Args:
        model (str, optional): The name of the OpenAI model to use. Defaults to "gpt-o-mini".
        temperature (float, optional): The temperature to use for the OpenAI model. Defaults to 0.
        token (SecretStr): The OpenAI API key.
        verbose (bool, optional): Whether to enable verbose logging. Defaults to False.

    Attributes:
        llm (ChatOpenAI): The initialized ChatOpenAI instance.
        _openai_semaphore (asyncio.Semaphore): Asynchronous semaphore to manage concurrent API calls.
        _chain (LLMChain, optional): The Langchain LLMChain to use for invoking the model.
        _total_cost (float): Monitor openai expense.

    Methods:
        async invoke_llm(question: str, sections: dict, pubmed_id: str = None) -> dict | None: Asynchronously invokes the LLM with the given question and sections.  Returns the LLM's response or None if an error occurs.
    """
    model: str = "gpt-o-mini"
    temperature: float = 0.0
    token: SecretStr
    verbose: bool = False
    
    _chain: LLMChain = None # Requires setting this before use

    _total_cost: float = 0

    _openai_semaphore: asyncio.Semaphore = asyncio.Semaphore(5)

    @computed_field
    @cached_property
    def llm(self) -> ChatOpenAI:
        """Initializes and configures the ChatOpenAI instance."""
        llm = ChatOpenAI(
            model_name=self.model,
            temperature=self.temperature,
            openai_api_key=self.token.get_secret_value(),  # type: ignore
            max_tokens=None,
        )
        if self.verbose:
            llm = llm.with_config({"callbacks": [ConsoleCallbackHandler()]})
        return llm
    
    @computed_field
    @cached_property
    def valid_key(self) -> bool:
        try:
            response = self.llm.invoke("Hello, how are you?")
            return True
        except AuthenticationError:
            logger.error(f"Your openai key is invalid")
            return False
            
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_random(min=0.1, max=0.5),
        retry_error_callback=lambda _: (_ for _ in ()).throw(httpx.ConnectError("Looks like Openai is down!"))
    )
    async def invoke_llm(self, research_question: str, sections: dict, pubmed_id: str = None) -> dict | None:
        """
        Asynchronously invokes the LLM with the given question and sections.

        Args:
            question (str): The question to ask the LLM.
            sections (dict): The sections of text to provide as context to the LLM.
            pubmed_id (str, optional): The PubMed ID for logging purposes. Defaults to None.

        Returns:
            dict | None: The LLM's response, or None if an error occurs.
        """
        if not self.valid_key:
            return None

        async with self._openai_semaphore:
            with get_openai_callback() as cb:
                try:
                    result = await self._chain.ainvoke(
                        {
                            "research_question": research_question,
                            "sections": sections,
                        }
                    )
                    self._total_cost += cb.total_cost

                    logger.debug(f"Successfully extracted features for {pubmed_id} at a cost of {cb.total_cost}")
                    return result # Extract the actual result from the chain output.
                
                except OutputParserException as e:
                    logger.error(f"Parsing error for {pubmed_id}\n {e}")
                    return None
