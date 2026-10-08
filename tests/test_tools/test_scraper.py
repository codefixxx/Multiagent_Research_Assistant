"""Unit tests for the deep web page scraper."""

import httpx
import pytest

from src.schemas.finding import ExtractionStatus
from src.tools.scraper import DeepPageScraper


@pytest.mark.asyncio
async def test_scrape_page_success(monkeypatch):
    sample_html = """
    <!DOCTYPE html>
    <html>
      <head><title>Redis vs Memcached Latency Guide</title></head>
      <body>
        <nav><a href="/">Home</a></nav>
        <article>
          <h1>Benchmark Results</h1>
          <p>Redis delivers sub-millisecond latency for typical read and write operations.</p>
          <p>Memcached demonstrates higher throughput for pure multithreaded caching workloads.</p>
        </article>
        <footer>Copyright 2026</footer>
      </body>
    </html>
    """

    class MockResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        text = sample_html

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

    scraper = DeepPageScraper(timeout=5.0, max_words_per_page=100)
    doc = await scraper.scrape_page("https://example.com/benchmarks")

    assert doc.status == ExtractionStatus.SUCCESS
    assert "Redis" in doc.raw_text
    assert "Benchmark Results" in doc.raw_text or "Redis delivers" in doc.raw_text
    assert doc.word_count > 0
    assert doc.title == "Redis vs Memcached Latency Guide"


@pytest.mark.asyncio
async def test_scrape_page_blocked_403(monkeypatch):
    class MockResponse:
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
            return MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    scraper = DeepPageScraper()
    doc = await scraper.scrape_page("https://example.com/protected")

    assert doc.status == ExtractionStatus.BLOCKED
    assert "403" in (doc.error_message or "")


@pytest.mark.asyncio
async def test_scrape_page_rate_limited_429(monkeypatch):
    class MockResponse:
        status_code = 429
        headers = {"content-type": "text/html"}
        reason_phrase = "Too Many Requests"

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

    scraper = DeepPageScraper()
    doc = await scraper.scrape_page("https://example.com/api-docs")

    assert doc.status == ExtractionStatus.RATE_LIMITED


@pytest.mark.asyncio
async def test_scrape_page_timeout(monkeypatch):
    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            raise httpx.TimeoutException("Timed out")

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    scraper = DeepPageScraper()
    doc = await scraper.scrape_page("https://example.com/slow-endpoint")

    assert doc.status == ExtractionStatus.TIMED_OUT


@pytest.mark.asyncio
async def test_scrape_page_content_truncation(monkeypatch):
    words = "word " * 500
    sample_html = f"<html><head><title>Long Page</title></head><body><p>{words}</p></body></html>"

    class MockResponse:
        status_code = 200
        headers = {"content-type": "text/html"}
        text = sample_html

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

    scraper = DeepPageScraper(max_words_per_page=50)
    doc = await scraper.scrape_page("https://example.com/long-page")

    assert doc.status == ExtractionStatus.SUCCESS
    assert doc.word_count == 50
    assert "[Content truncated at 50 words" in doc.raw_text


@pytest.mark.asyncio
async def test_scrape_multiple_concurrent(monkeypatch):
    class MockResponse:
        status_code = 200
        headers = {"content-type": "text/html"}
        text = "<html><body><p>Clean extracted page text for concurrency test.</p></body></html>"

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

    scraper = DeepPageScraper()
    docs = await scraper.scrape_multiple(
        ["https://example.com/1", "https://example.com/2", "https://example.com/3"],
        max_concurrency=2,
    )

    assert len(docs) == 3
    assert all(d.status == ExtractionStatus.SUCCESS for d in docs)
