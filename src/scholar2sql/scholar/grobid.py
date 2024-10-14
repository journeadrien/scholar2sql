import asyncio
from pathlib import Path
import httpx
from tenacity import retry, stop_after_attempt, retry_if_exception_type, wait_random
from pydantic import BaseModel, model_validator
from scholaretl.article_parser import TEIXMLParser
from scholaretl.article import Article
import logging

logger = logging.getLogger(__name__)

RETRY_EXCEPTIONS = (
    httpx.ConnectTimeout, 
    httpx.RemoteProtocolError, 
    httpx.ReadTimeout, 
    httpx.ConnectError, 
    httpx.ReadError,
    ValueError
)

class GrobidAPIWrapper(BaseModel):
    """
    Wrapper around GROBID API for parsing PDFs and Unpaywall API for fetching PDF URLs.

    This wrapper uses the GROBID API to parse PDFs into structured XML (TEI) format,
    and the Unpaywall API to find open access PDF URLs.

    Attributes:
        url (str): URL of the GROBID service.
        min_pdf_size (int): Minimum acceptable size for downloaded PDFs in bytes.
        tmp_pdf_folder (Path): Temporary folder to store downloaded PDFs.
        tmp_tei_folder (Path): Temporary folder to store parsed TEI XML files.
    """

    url: str = None
    email: str = None
    min_pdf_size: int = 10000
    tmp_pdf_folder: Path = Path("tmp/pdf")
    tmp_tei_folder: Path = Path("tmp/tei")

    _grobid_semaphore: asyncio.Semaphore = asyncio.Semaphore(1)
    _pdf_semaphore: asyncio.Semaphore = asyncio.Semaphore(100)

    @model_validator(mode="after")
    def val_model_after(self):
        self.tmp_pdf_folder.mkdir(parents=True, exist_ok=True)
        self.tmp_tei_folder.mkdir(parents=True, exist_ok=True)
        return self

    @property
    def is_connected(self):
        try:
            _ = httpx.get(f"{self.url}/api/version")
            return True
        except httpx.ConnectError:
            logger.error(f"grobid with url: {self.url} can't be access.")
        return False

    @retry(
        retry=retry_if_exception_type(RETRY_EXCEPTIONS),
        stop=stop_after_attempt(5),
        wait=wait_random(min=0.1, max=0.5)
    )
    async def parse_pdf_with_grobid(self, pubmed_id: str, pdf_path: Path) -> Article | None:
        """
        Parse a PDF file using GROBID and return an Article object.

        Args:
            pubmed_id (str): PubMed ID of the article.
            pdf_path (Path): Path to the PDF file.

        Returns:
            Article | None: Parsed Article object if successful, None otherwise.
        """
        tei_path = self.tmp_tei_folder / f"{pubmed_id}.tei"

        if tei_path.exists():
            return self._load_existing_tei(tei_path)

        if not self.url or not pdf_path.exists() or not self.is_connected:
            return None

        async with self._grobid_semaphore:
            tei_content = await self._send_pdf_to_grobid(pdf_path)

        if tei_content:
            self._save_tei(tei_path, tei_content)
            return self._parse_tei(tei_path)

        return None

    @retry(
        retry=retry_if_exception_type(RETRY_EXCEPTIONS),
        stop=stop_after_attempt(5),
        wait=wait_random(min=0.1, max=0.5)
    )
    async def download_and_parse_pdf(self, pubmed_id: str, doi: str) -> Article | None:
        """
        Download a PDF for a given DOI and parse it using GROBID.

        Args:
            pubmed_id (str): PubMed ID of the article.
            doi (str): DOI of the article.

        Returns:
            Article | None: Parsed Article object if successful, None otherwise.
        """
        pdf_path = self.tmp_pdf_folder / f"{pubmed_id}.pdf"

        if pdf_path.exists():
            return await self.parse_pdf_with_grobid(pubmed_id, pdf_path)

        async with self._pdf_semaphore:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=60.0)) as client:
                pdf_urls = self._get_pdf_urls_from_unpaywall(doi)
                for pdf_url in pdf_urls:
                    success = await self._download_pdf(client, pdf_url, pdf_path)
                    if success:
                        break

        if pdf_path.exists() and pdf_path.stat().st_size > self.min_pdf_size:
            return await self.parse_pdf_with_grobid(pubmed_id, pdf_path)

        return None

    @retry(
        retry=retry_if_exception_type(RETRY_EXCEPTIONS),
        stop=stop_after_attempt(5),
        wait=wait_random(min=0.1, max=0.5)
    )
    def _get_pdf_urls_from_unpaywall(self, doi: str) -> str | None:
        """
        Get the PDF URL for a given DOI using the Unpaywall API.

        Args:
            client (httpx.AsyncClient): Async HTTP client.
            doi (str): DOI of the article.

        Returns:
            str | None: URL of the PDF if found, None otherwise.
        """
        response = httpx.get(
            f'https://api.unpaywall.org/v2/{doi}',
            params={'email': self.email},
            #verify=False  # TODO: Remove this in production
        )
        data = response.json()
        pdf_urls = []
        for key, value in data.items():
            if key.endswith('oa_location') and value and value.get("url_for_pdf"):
                pdf_urls.append(value["url_for_pdf"])
        return pdf_urls

    async def _send_pdf_to_grobid(self, pdf_path: Path) -> str | None:
        """Send a PDF to GROBID for parsing."""
        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()

        response = await httpx.AsyncClient().post(
            f"{self.url}/api/processFulltextDocument",
            files={"input": pdf_content},
            headers={"Accept": "application/xml"},
            timeout=httpx.Timeout(10.0, connect=60.0)
        )

        if response.status_code == 429:
            raise httpx.ConnectTimeout("Error 429: Too Many Requests")

        response.raise_for_status()
        return response.text

    async def _download_pdf(self, client: httpx.AsyncClient, url: str, path: Path) -> None:
        """Download a PDF from a given URL and check if it is not empty."""
        response = await client.get(url, follow_redirects=True)
        path.write_bytes(response.content)
        if path.stat().st_size <= self.min_pdf_size:
            path.unlink()
            logger.debug(f"Downloaded PDF for {path.stem} is too small; deleting.")
            return False
        logger.debug(f"Successfully downloaded PDF for {path.stem}")
        return True

    @staticmethod
    def _load_existing_tei(path: Path) -> Article | None:
        """Load an existing TEI file and parse it into an Article object."""
        logger.debug(f"Found TEI file for {path.stem} in tmp folder")
        with open(path, 'rb') as f:
            article = Article.parse(TEIXMLParser(f.read()))
        return article if article.abstract else None

    @staticmethod
    def _save_tei(path: Path, content: str) -> None:
        """Save TEI content to a file."""
        with open(path, 'w') as f:
            f.write(content)

    @staticmethod
    def _parse_tei(path: Path) -> Article | None:
        """Parse a TEI file into an Article object."""
        with open(path, 'rb') as f:
            article = Article.parse(TEIXMLParser(f.read()))
        return article if article.abstract else None