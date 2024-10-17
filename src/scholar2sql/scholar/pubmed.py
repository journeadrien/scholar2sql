from pydantic import BaseModel, model_validator
import httpx
from pathlib import Path
from typing import Optional, List
import asyncio
from httpx import ConnectTimeout, RemoteProtocolError, ReadTimeout, ConnectError, ReadError
from tenacity import retry, stop_after_attempt, retry_if_exception_type, wait_random
import xml.etree.ElementTree as ET
from scholaretl.article_parser import JATSXMLParser, PubMedXMLParser
from scholaretl.article import Article
from bs4 import BeautifulSoup
import logging

retry_on_error = (
    httpx.ConnectTimeout, 
    httpx.RemoteProtocolError, 
    httpx.ReadTimeout, 
    httpx.ConnectError, 
    httpx.ReadError,
    ValueError,
    ET.ParseError
)

def pubmed_down(retry_state):
    logger.log(
        logging.ERROR, 'Retrying %s: attempt %s ended with: %s, looks like pubmed is down!',
        retry_state.fn, retry_state.attempt_number, retry_state.outcome)
    raise httpx.ConnectError("Looks like pubmed is down!")

logger = logging.getLogger(__name__)

class PubMedAPIWrapper(BaseModel):
    """
    A Wrapper around the PubMed API to conduct searches and fetch document summaries.

    Parameters:
        api_key: API key for the PubMed API (optional)
        email: Email address to be used for the PubMed API
        top_articles_per_search: Number of top-scored documents to fetch (default: 100)
        additional_search_keywords: additional search keywords
        tmp_pmc_folder: Path to the temporary folder for storing PMC documents (default: "tmp/pmc")
        tmp_abstract_folder: Path to the temporary folder for storing abstracts (default: "tmp/abstract")
    """

    api_key: str = ""
    email: str = ""
    top_articles_per_search: int = 10
    additional_search_keywords: str = ""
    tmp_pmc_folder: Path = Path("tmp/pmc")
    tmp_abstract_folder: Path = Path("tmp/abstract")

    _pmc_semaphore: asyncio.Semaphore = asyncio.Semaphore(100)
    _pubmed_semaphore: asyncio.Semaphore = asyncio.Semaphore(10)


    @model_validator(mode="after")
    def val_model_after(self):
        self.tmp_pmc_folder.mkdir(parents=True, exist_ok=True)
        self.tmp_abstract_folder.mkdir(parents=True, exist_ok=True)
        return self

    @retry(
        retry=retry_if_exception_type(retry_on_error),
        stop=stop_after_attempt(5),
        wait=wait_random(min=0.1, max=0.5),
        retry_error_callback=lambda _: (_ for _ in ()).throw(httpx.ConnectError("Looks like PMC is down!"))
    )
    async def convert_pubmed_to_pmc_id(self, pubmed_id: str) -> Optional[str]:
        """
        Convert a PubMed ID to a PubMed Central (PMC) ID.

        Parameters:
            pubmed_id: The PubMed ID to convert.

        Returns:
            The corresponding PMC ID, or None if not found.
        """
        params = {
            "tool": "my_tool",
            "email": self.email,
            "ids": pubmed_id,
            "format": "json"
        }

        response = httpx.get(
            url="https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
            params=params
        )
        json_data = response.json()
        if response.status_code == 429:
            raise ConnectTimeout("error 429")
        try:
            pmc_id = json_data["records"][0]["pmcid"]
            logger.debug(f"Successfully converted PubMed ID {pubmed_id} to PMC ID")
            return pmc_id
        except (IndexError, KeyError):
            #logger.debug(f"Failed to convert PubMed ID {pubmed_id} to PMC ID")
            return None
        except Exception as e:
            logger.error(f"Error getting pmc id for {pubmed_id}: {e}")
            return None

    @retry(
        retry=retry_if_exception_type(retry_on_error + (KeyError, )),
        stop=stop_after_attempt(5),
        wait=wait_random(min=0.1, max=0.5),
        retry_error_callback=lambda _: (_ for _ in ()).throw(httpx.ConnectError("Looks like pubmed is down!"))
    )
    async def search_pubmed(self, query: str) -> List[str]:
        """
        Search PubMed for the given query and return the list of PubMed IDs.

        Parameters:
            query: The search query.

        Returns:
            A list of PubMed IDs.
        """
        query = query + " " + self.additional_search_keywords
        params = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": self.top_articles_per_search,
            "usehistory": "y"
        }
        if self.api_key:
            params["api_key"] = self.api_key
        
        logger.debug(f"Searching PubMed for papers matching '{query}'")
        async with self._pubmed_semaphore:
            response = httpx.get(
                url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params=params,
                timeout=httpx.Timeout(10.0, connect=60.0)
            )

            response.raise_for_status()
            json_data = response.json()
        pubmed_ids = json_data["esearchresult"]["idlist"]
        logger.info(f"Successfully found {len(pubmed_ids)} papers for '{query}'")
        return pubmed_ids
        return []
        
    @retry(
        retry=retry_if_exception_type(retry_on_error+(IndexError,)),
        stop=stop_after_attempt(5),
        wait=wait_random(min=0.1, max=0.5),
        retry_error_callback=lambda _: (_ for _ in ()).throw(httpx.ConnectError("Looks like Pubmed is down!"))
    )
    async def get_pubmed_abstract(self, pubmed_id: str) -> Optional[Article]:
        """
        Fetch the abstract for the given PubMed ID and return it as an Article object.

        Parameters:
            pubmed_id: The PubMed ID to fetch the abstract for.

        Returns:
            The Article object containing the abstract, or None if not found.
        """
        saving_path = self.tmp_abstract_folder / f"{pubmed_id}.xml"

        # Load the abstract from the temporary folder if it exists
        if saving_path.exists():
            logger.debug(f"Found abstract file for {pubmed_id} in tmp folder")
            with open(saving_path, 'rb') as f:
                article = Article.parse(PubMedXMLParser(f.read()))
            if article.abstract:
                return article

        params = {
            "db": "pubmed",
            "id": pubmed_id,
            "retmode": "xml"
        }
        if self.api_key:
            params["api_key"] = self.api_key
        
        async with self._pubmed_semaphore:
            response = httpx.get(
                url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                params=params,
                timeout=httpx.Timeout(10.0, connect=60.0)
            )
            
        if response.status_code == 429:
            raise httpx.ConnectTimeout("error 429")
        xml = ET.fromstring(response.content)
        # For compatibility with JATS ETL parsing
        xml = ET.ElementTree(xml.findall('PubmedArticle')[0])
        xml.write(saving_path)
        logger.info(f"Successfully downloaded abstract of {pubmed_id}")
        
        # Load the abstract from the temporary folder
        if saving_path.exists():
            logger.debug(f"Abstract loaded for {pubmed_id} in tmp folder")
            with open(saving_path, 'rb') as f:
                article = Article.parse(PubMedXMLParser(f.read()))
            if article.abstract:
                return article
        return None
    
    @retry(
        retry=retry_if_exception_type(retry_on_error),
        stop=stop_after_attempt(5),
        wait=wait_random(min=0.1, max=0.5),
        retry_error_callback=lambda _: (_ for _ in ()).throw(httpx.ConnectError("Looks like PMC is down!"))
    )
    async def get_pubmed_central(self, pubmed_id: str) -> Optional[Article]:
        """
        Fetch the full-text article from PubMed Central for the given PubMed ID and return it as an Article object.

        Parameters:
            pubmed_id: The PubMed ID to fetch the full-text article for.

        Returns:
            The Article object containing the full-text article, or None if not found.
        """
        saving_path = self.tmp_pmc_folder / f"{pubmed_id}.xml"

        # Load the article from the temporary folder if it exists
        if saving_path.exists():
            logger.debug(f"Found PMC file for {pubmed_id} in tmp folder")
            with open(saving_path, 'r') as f:
                article = Article.parse(JATSXMLParser.from_string(f))
            if article.abstract and article.section_paragraphs:
                return article

        pmc_id = await self.convert_pubmed_to_pmc_id(pubmed_id)
        if pmc_id is None:
            return None
        
        params = {
            "verb": "GetRecord",
            "identifier": f"oai:pubmedcentral.nih.gov:{pmc_id[3:]}",
            "metadataPrefix": "oai_dc"
        }

        async with self._pmc_semaphore:
            response =  httpx.get(
                url='https://www.ncbi.nlm.nih.gov/pmc/oai/oai.cgi',
                params=params,
                timeout=httpx.Timeout(10.0, connect=60.0)
            )
    
        if response.status_code == 429:
            raise ConnectTimeout("error 429")
        try:
            # Save the full-text article to the temporary folder
            xml_paper = BeautifulSoup(response.content, "xml")
            # For compatibility with JATS ETL parsing
            xml_paper = xml_paper.find_all('article')[0]
            if len(xml_paper.find_all('body')[0].find_all('sec')) < 2:
                return None
            # ETL parsing is expecting only these 2 attributes
            xml_paper.attrs = {key: value for key, value in xml_paper.attrs.items() if key in ["xmlns:xlink", "article-type", "xmlns:ali", "xmlns:mml"]}
            with open(saving_path, 'w') as f:
                f.write(xml_paper.prettify().replace('\n', ''))
            logger.info(f"Successfully found PMC full-text for {pubmed_id}")
        except (IndexError, ET.ParseError):
            logger.debug(f"Failed to parse full-text for {pubmed_id}")
            return None
        except Exception as e:
            logger.error(f"Error getting PMC full-text for {pubmed_id}: {e}")
            return None

        # Load the article from the temporary folder
        if saving_path.exists():
            logger.debug(f"PMC loaded for {pubmed_id} in tmp folder")
            with open(saving_path, 'r') as f:
                article = Article.parse(JATSXMLParser.from_string(f))
            if article.abstract and article.section_paragraphs:
                return article
        return None