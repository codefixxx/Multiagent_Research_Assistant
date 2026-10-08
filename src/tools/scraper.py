"""Deep web page scraper with boilerplate extraction and content truncation."""

import asyncio
import re
from typing import Any

import httpx
from pydantic import BaseModel, Field

from src.config import settings
from src.core.logger import logger
from src.schemas.finding import ExtractionStatus
from src.tools.errors import map_http_status_to_extraction_status

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)


class ScrapedDocument(BaseModel):
    """Clean extracted content and provenance metadata from a single webpage."""

    url: str = Field(description="Source URL scraped.")
    title: str = Field(default="Untitled", description="Page title.")
    raw_text: str = Field(default="", description="Clean boilerplate-free text content.")
    status: ExtractionStatus = Field(
        default=ExtractionStatus.SUCCESS,
        description="Outcome of the scrape attempt.",
    )
    error_message: str | None = Field(
        default=None,
        description="Error details if scrape failed.",
    )
    word_count: int = Field(default=0, description="Word count of extracted text.")


class DeepPageScraper:
    """Production asynchronous page scraper utilizing trafilatura for boilerplate removal."""

    def __init__(
        self,
        timeout: float | None = None,
        max_words_per_page: int | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        enable_jina_fallback: bool | None = None,
        jina_client: Any = None,
    ) -> None:
        self.timeout = timeout or settings.SCRAPER_TIMEOUT_SECONDS
        self.max_words = max_words_per_page or settings.SCRAPER_MAX_WORDS_PER_PAGE
        self.user_agent = user_agent
        self.enable_jina_fallback = (
            enable_jina_fallback
            if enable_jina_fallback is not None
            else settings.ENABLE_JINA_FALLBACK
        )
        self.jina_client = jina_client

    def _extract_title(self, html: str) -> str:
        """Extract title from HTML using regex fallback."""
        match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if match:
            clean = re.sub(r"\s+", " ", match.group(1)).strip()
            return clean[:200]
        return "Untitled Document"

    def _fallback_text_extraction(self, html: str) -> str:
        """Basic regex-based HTML text extractor when trafilatura yields no content."""
        # Strip script and style blocks
        clean = re.sub(
            r"<(script|style|nav|footer|header)[^>]*>.*?</\1>",
            "",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        # Strip all HTML tags
        clean = re.sub(r"<[^>]+>", " ", clean)
        # Collapse whitespace
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    def _truncate_content(self, text: str) -> tuple[str, int]:
        """Truncate text to max_words_per_page boundary."""
        words = text.split()
        total_words = len(words)
        if total_words <= self.max_words:
            return text, total_words

        truncated = " ".join(words[: self.max_words])
        notice = (
            f"\n\n[Content truncated at {self.max_words:,} words (total: {total_words:,} words)]"
        )
        return truncated + notice, self.max_words

    async def scrape_page(self, url: str) -> ScrapedDocument:
        """Fetch a webpage asynchronously, strip boilerplate, and return clean text."""
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            return ScrapedDocument(
                url=url,
                status=ExtractionStatus.ERROR,
                error_message="Invalid HTTP/HTTPS URL scheme",
            )

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers=headers,
            ) as client:
                response = await client.get(url)

            # Check HTTP Status Code
            if response.status_code != 200:
                status = map_http_status_to_extraction_status(response.status_code)
                if self.enable_jina_fallback and status in (
                    ExtractionStatus.BLOCKED,
                    ExtractionStatus.PAYWALLED,
                    ExtractionStatus.ERROR,
                ):
                    logger.info(
                        "Direct scrape returned error; trying Jina Reader fallback",
                        url=url,
                        status_code=response.status_code,
                    )
                    from src.tools.jina_reader import JinaReaderClient

                    jina = self.jina_client or JinaReaderClient(max_words=self.max_words)
                    jina_doc = await jina.read_url(url)
                    if jina_doc.status == ExtractionStatus.SUCCESS:
                        return jina_doc

                return ScrapedDocument(
                    url=url,
                    status=status,
                    error_message=f"HTTP {response.status_code}: {response.reason_phrase}",
                )

            # Validate Content-Type
            content_type = response.headers.get("content-type", "").lower()
            if content_type and not any(
                t in content_type for t in ("text/html", "application/xhtml", "text/plain")
            ):
                return ScrapedDocument(
                    url=url,
                    status=ExtractionStatus.BLOCKED,
                    error_message=f"Unsupported non-HTML content type: {content_type}",
                )

            html_content = response.text
            title = self._extract_title(html_content)

            # Extract clean main text using trafilatura
            import trafilatura

            extracted_text = trafilatura.extract(
                html_content,
                include_links=False,
                include_comments=False,
                output_format="txt",
            )

            if not extracted_text or not extracted_text.strip():
                extracted_text = self._fallback_text_extraction(html_content)

            if not extracted_text or not extracted_text.strip():
                if self.enable_jina_fallback:
                    logger.info(
                        "Direct scrape yielded no readable text; trying Jina Reader fallback",
                        url=url,
                    )
                    from src.tools.jina_reader import JinaReaderClient

                    jina = self.jina_client or JinaReaderClient(max_words=self.max_words)
                    jina_doc = await jina.read_url(url)
                    if jina_doc.status == ExtractionStatus.SUCCESS:
                        return jina_doc

                return ScrapedDocument(
                    url=url,
                    title=title,
                    status=ExtractionStatus.NO_RESULTS,
                    error_message="No readable main text extracted from webpage",
                )

            clean_text, word_count = self._truncate_content(extracted_text)

            logger.info(
                "Page scraped successfully",
                url=url,
                title=title[:40],
                words=word_count,
            )

            return ScrapedDocument(
                url=url,
                title=title,
                raw_text=clean_text,
                status=ExtractionStatus.SUCCESS,
                word_count=word_count,
            )

        except httpx.TimeoutException:
            logger.warning("Scraper timed out fetching URL", url=url, timeout=self.timeout)
            return ScrapedDocument(
                url=url,
                status=ExtractionStatus.TIMED_OUT,
                error_message=f"Request timed out after {self.timeout:.1f}s",
            )
        except httpx.HTTPStatusError as e:
            status = map_http_status_to_extraction_status(e.response.status_code)
            return ScrapedDocument(
                url=url,
                status=status,
                error_message=str(e),
            )
        except Exception as e:
            logger.warning("Scraper failed fetching URL", url=url, error=str(e))
            return ScrapedDocument(
                url=url,
                status=ExtractionStatus.ERROR,
                error_message=str(e),
            )

    async def scrape_multiple(
        self,
        urls: list[str],
        max_concurrency: int = 5,
    ) -> list[ScrapedDocument]:
        """Scrape multiple URLs concurrently with bounded concurrency."""
        if not urls:
            return []

        semaphore = asyncio.Semaphore(max_concurrency)

        async def _bounded_scrape(target_url: str) -> ScrapedDocument:
            async with semaphore:
                return await self.scrape_page(target_url)

        tasks = [_bounded_scrape(u) for u in urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return list(results)
