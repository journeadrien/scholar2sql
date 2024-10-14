from pydantic import BaseModel, model_validator
from .pubmed import PubMedAPIWrapper
from .grobid import GrobidAPIWrapper
from ..metadata import Metadata
import asyncio
from typing import AsyncIterator, Tuple
import logging
from scholaretl.article import Article
from bm25s import tokenize, BM25, debug_logger
import Stemmer

debug_logger.setLevel(logging.ERROR) #bm25s not very well written there, level is hardcoded to debug
logger = logging.getLogger(__name__)

class Scholar(BaseModel):
    """
    A class that retrieves and processes scholarly articles from PubMed and GROBID.

    Attributes:
        pubmed (PubMedAPIWrapper): An instance of the PubMedAPIWrapper class.
        grobid (GrobidAPIWrapper): An instance of the GrobidAPIWrapper class.
        top_sections_per_article (int): The maximum number of sections to retrieve for each article.
        email (str): The email address to be used for the PubMed and GROBID APIs.
    """
    pubmed: PubMedAPIWrapper
    grobid: GrobidAPIWrapper
    top_sections_per_article: int = 5
    email: str

    @model_validator(mode="after")
    def val_model_after(self):
        self.grobid.email = self.email
        self.pubmed.email = self.email
        return self

    async def retrieve_one_article(self, pubmed_id: str) -> Tuple[Article, Metadata]:
        """
        Retrieves a single article from PubMed and GROBID based on the provided PubMed ID.

        Args:
            pubmed_id (str): The PubMed ID of the article to retrieve.

        Returns:
            Tuple[Article, Metadata]: A tuple containing the retrieved article and its metadata.
        """
        metadata = Metadata().update_from_dict({"pubmed_id": pubmed_id})

        article = await self.pubmed.get_pubmed_central(pubmed_id)
        if article is not None:
            metadata.format.value = "PMC"
            return article, metadata

        article = await self.pubmed.get_pubmed_abstract(pubmed_id)
        if article is None:
            return None, None

        metadata.format.value = "PUBMED"
        if article.doi is not None:
            article_pdf = await self.grobid.download_and_parse_pdf(pubmed_id, article.doi)
            if article_pdf is not None and article_pdf.section_paragraphs:
                metadata.format.value += " | PDF"
                article.section_paragraphs = article_pdf.section_paragraphs

        return article, metadata

    def get_top_sections(self, article: Article, research_question: str) -> dict:
        """
        Retrieves the top-k most relevant sections of an article based on the given question.

        Args:
            article (Article): The article to search.
            research_question (str): The research_question to use for the search.

        Returns:
            dict: A dictionary mapping section numbers to the corresponding section text.
        """
        docs = article.abstract + [section[1] for section in article.section_paragraphs]

        if len(docs) <= self.top_sections_per_article:
            return {f"section_{i+1}": paragraph for i, paragraph in enumerate(docs)}

        stemmer = Stemmer.Stemmer("english")
        docs_tokens = tokenize(texts=docs, stopwords="en", stemmer=stemmer, show_progress=False)
        retriever = BM25()
        retriever.index(corpus=docs_tokens, show_progress=False)

        question_tokens = tokenize(research_question, stemmer=stemmer)
        results, scores = retriever.retrieve(query_tokens=question_tokens, corpus=docs, k=self.top_sections_per_article, show_progress=False)

        logger.debug(f"Get top_k docs for {article.pubmed_id} with scores {scores[0]}")
        return {f"section_{i+1}": paragraph for i, paragraph in enumerate(results[0])}

    async def iter(self, pubmed_query: str) -> AsyncIterator[Tuple[Article, Metadata]]:
        """
        Retrieves a stream of articles and their metadata based on the provided PubMed query.

        Args:
            pubmed_query (str): The PubMed query to use for the search.

        Yields:
            Tuple[Article, Metadata]: A tuple containing the retrieved article and its metadata.
        """
        tasks = [
            asyncio.ensure_future(self.retrieve_one_article(pubmed_id))
            for pubmed_id in await self.pubmed.search_pubmed(pubmed_query)
        ]
        for task in asyncio.as_completed(tasks):
            article, metadata = await task
            if article is not None and (article.abstract or article.section_paragraphs):
                yield article, metadata
