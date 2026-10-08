"""Unit tests for Jina Reader client and scraper unblocking fallback."""

import httpx
import pytest

from src.schemas.finding import ExtractionStatus
from src.tools.jina_reader import JinaReaderClient
from src.tools.scraper import DeepPageScraper, ScrapedDocument


@pytest.mark.asyncio
async def test_jina_reader_success(monkeypatch):
    sample_jina_markdown = """
Title: Advanced Redis Concurrency Architecture

URL Source: https://example.com/redis-concurrency

Markdown Content:
## Threading Overview

Redis uses an event loop with epoll for high-performance single-threaded command processing.
I/O threading was introduced to parallelize socket reading and writing.
"""

    class MockResponse:
        status_code = 200
        text = sample_jina_markdown

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            return MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    client = JinaReaderClient(max_words=100)
    doc = await client.read_url("https://example.com/redis-concurrency")

    assert doc.status == ExtractionStatus.SUCCESS
    assert doc.title == "Advanced Redis Concurrency Architecture"
    assert "Redis uses an event loop" in doc.raw_text
    assert doc.word_count > 0


@pytest.mark.asyncio
async def test_jina_reader_timeout(monkeypatch):
    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            raise httpx.TimeoutException("Jina request timed out")

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    client = JinaReaderClient()
    doc = await client.read_url("https://example.com/slow-page")

    assert doc.status == ExtractionStatus.TIMED_OUT
    assert "timed out" in (doc.error_message or "").lower()


@pytest.mark.asyncio
async def test_jina_reader_truncation(monkeypatch):
    long_content = "Title: Long Page\n\nMarkdown Content:\n" + ("word " * 500)

    class MockResponse:
        status_code = 200
        text = long_content

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            return MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    client = JinaReaderClient(max_words=50)
    doc = await client.read_url("https://example.com/long-page")

    assert doc.status == ExtractionStatus.SUCCESS
    assert doc.word_count == 50
    assert "[Content truncated at 50 words" in doc.raw_text


@pytest.mark.asyncio
async def test_scraper_fallback_to_jina_when_blocked(monkeypatch):
    """When direct scrape encounters HTTP 403, DeepPageScraper automatically unblocks via Jina."""

    class StubJinaClient:
        async def read_url(self, url: str) -> ScrapedDocument:
            return ScrapedDocument(
                url=url,
                title="Unblocked Medium Article via Jina",
                raw_text="Successfully extracted text through Jina Reader proxy.",
                status=ExtractionStatus.SUCCESS,
                word_count=8,
            )

    class MockResponse403:
        status_code = 403
        headers = {"content-type": "text/html"}
        reason_phrase = "Forbidden"

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            return MockResponse403()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    scraper = DeepPageScraper(
        enable_jina_fallback=True,
        jina_client=StubJinaClient(),
    )

    doc = await scraper.scrape_page("https://medium.com/@author/redis-guide")

    assert doc.status == ExtractionStatus.SUCCESS
    assert doc.title == "Unblocked Medium Article via Jina"
    assert "extracted text through Jina" in doc.raw_text
