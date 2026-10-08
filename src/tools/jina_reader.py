"""Jina Reader Client for converting web pages into clean Markdown."""

import re

import httpx

from src.config import settings
from src.core.logger import logger
from src.schemas.finding import ExtractionStatus
from src.tools.errors import map_http_status_to_extraction_status
from src.tools.scraper import ScrapedDocument


class JinaReaderClient:
    """Client for Jina Reader API (https://r.jina.ai/) providing high-fidelity Markdown extraction."""

    BASE_URL = "https://r.jina.ai"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 12.0,
        max_words: int | None = None,
    ) -> None:
        self.api_key = api_key or settings.JINA_API_KEY
        self.timeout = timeout
        self.max_words = max_words or settings.SCRAPER_MAX_WORDS_PER_PAGE

    def _parse_jina_markdown(self, raw_markdown: str) -> tuple[str, str]:
        """Extract title and main content from Jina Reader markdown output."""
        title = "Untitled Document"
        title_match = re.search(r"^Title:\s*(.+)$", raw_markdown, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()

        # If Jina formatted with 'Markdown Content:', take everything after it
        content_split = re.split(r"Markdown Content:\s*", raw_markdown, maxsplit=1)
        if len(content_split) > 1:
            body = content_split[1].strip()
        else:
            # Otherwise remove metadata header lines if present
            body = re.sub(
                r"^(Title|URL Source|Published Time):\s*.+\n*",
                "",
                raw_markdown,
                flags=re.MULTILINE,
            ).strip()

        return title, body

    def _truncate_content(self, text: str) -> tuple[str, int]:
        """Truncate text to max_words boundary."""
        words = text.split()
        total_words = len(words)
        if total_words <= self.max_words:
            return text, total_words

        truncated = " ".join(words[: self.max_words])
        notice = (
            f"\n\n[Content truncated at {self.max_words:,} words (total: {total_words:,} words)]"
        )
        return truncated + notice, self.max_words

    async def read_url(self, url: str) -> ScrapedDocument:
        """Fetch and convert a URL into clean Markdown via Jina Reader."""
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            return ScrapedDocument(
                url=url,
                status=ExtractionStatus.ERROR,
                error_message="Invalid HTTP/HTTPS URL scheme",
            )

        jina_url = f"{self.BASE_URL}/{url}"
        headers: dict[str, str] = {
            "Accept": "text/plain, text/markdown",
            "X-Timeout": str(int(self.timeout)),
            "X-Return-Format": "markdown",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers=headers,
            ) as client:
                response = await client.get(jina_url)

            if response.status_code != 200:
                status = map_http_status_to_extraction_status(response.status_code)
                return ScrapedDocument(
                    url=url,
                    status=status,
                    error_message=f"Jina Reader returned HTTP {response.status_code}: {response.reason_phrase}",
                )

            raw_text = response.text
            if not raw_text or not raw_text.strip():
                return ScrapedDocument(
                    url=url,
                    status=ExtractionStatus.NO_RESULTS,
                    error_message="Jina Reader returned empty content",
                )

            title, clean_body = self._parse_jina_markdown(raw_text)
            clean_text, word_count = self._truncate_content(clean_body)

            logger.info(
                "Jina Reader successfully extracted page",
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
            logger.warning("Jina Reader request timed out", url=url, timeout=self.timeout)
            return ScrapedDocument(
                url=url,
                status=ExtractionStatus.TIMED_OUT,
                error_message=f"Jina Reader timed out after {self.timeout:.1f}s",
            )
        except Exception as e:
            logger.warning("Jina Reader request failed", url=url, error=str(e))
            return ScrapedDocument(
                url=url,
                status=ExtractionStatus.ERROR,
                error_message=str(e),
            )
