"""Unit tests for search engine clients and fallback orchestration."""

import httpx
import pytest

from src.schemas.finding import ExtractionStatus
from src.tools.errors import SearchError
from src.tools.search import (
    DuckDuckGoSearchClient,
    MockSearchClient,
    MultiSearchClient,
    SearchResult,
    TavilySearchClient,
)


@pytest.mark.asyncio
async def test_mock_search_client_default():
    client = MockSearchClient()
    results = await client.search("Redis clustering", max_results=2)
    assert len(results) == 2
    assert all(isinstance(r, SearchResult) for r in results)
    assert "Redis clustering" in results[0].title
    assert results[0].engine == "mock"


@pytest.mark.asyncio
async def test_tavily_search_success(monkeypatch):
    class MockResponse:
        status_code = 200

        def json(self):
            return {
                "results": [
                    {
                        "title": "Redis vs Memcached Latency Benchmark",
                        "url": "https://redis.io/benchmarks",
                        "content": "Redis benchmark shows sub-millisecond p99 latencies.",
                        "score": 0.98,
                    }
                ]
            }

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json):
            return MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    client = TavilySearchClient(api_key="test-api-key")
    results = await client.search("Redis latency", max_results=1)

    assert len(results) == 1
    assert results[0].title == "Redis vs Memcached Latency Benchmark"
    assert results[0].url == "https://redis.io/benchmarks"
    assert results[0].engine == "tavily"


@pytest.mark.asyncio
async def test_tavily_search_rate_limited(monkeypatch):
    class MockResponse:
        status_code = 429
        text = "Rate limit exceeded"

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json):
            return MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    client = TavilySearchClient(api_key="test-api-key")
    with pytest.raises(SearchError) as exc_info:
        await client.search("Redis latency")

    assert exc_info.value.status == ExtractionStatus.RATE_LIMITED


@pytest.mark.asyncio
async def test_duckduckgo_search_success(monkeypatch):
    sample_ddg_results = [
        {
            "title": "Memcached Multithreaded Architecture",
            "href": "https://memcached.org/arch",
            "body": "Memcached scales efficiently on multiple CPU cores.",
        }
    ]

    class FakeDDGS:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def text(self, query, max_results=5):
            return sample_ddg_results

    try:
        monkeypatch.setattr("ddgs.DDGS", FakeDDGS)
    except Exception:
        pass
    try:
        monkeypatch.setattr("duckduckgo_search.DDGS", FakeDDGS)
    except Exception:
        pass

    client = DuckDuckGoSearchClient()
    results = await client.search("Memcached multithreading", max_results=1)

    assert len(results) == 1
    assert results[0].title == "Memcached Multithreaded Architecture"
    assert results[0].engine == "duckduckgo"


@pytest.mark.asyncio
async def test_multi_search_client_fallback(monkeypatch):
    # Simulate Tavily failing and falling back to DuckDuckGo
    class FailingTavily(TavilySearchClient):
        async def search(self, query, max_results=5):
            raise SearchError("Tavily down", status=ExtractionStatus.ERROR)

    class WorkingDDG(DuckDuckGoSearchClient):
        async def search(self, query, max_results=5):
            return [
                SearchResult(
                    title="DDG Result",
                    url="https://ddg.example.com",
                    snippet="Found via DDG fallback",
                    engine="duckduckgo",
                )
            ]

    multi = MultiSearchClient(
        tavily_client=FailingTavily(),
        ddg_client=WorkingDDG(),
    )

    results, status = await multi.search("Test query", max_results=1)
    assert len(results) == 1
    assert results[0].engine == "duckduckgo"
    assert status == ExtractionStatus.SUCCESS
