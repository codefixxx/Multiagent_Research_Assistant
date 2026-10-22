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


@pytest.mark.asyncio
async def test_focus_mode_domain_biasing(monkeypatch):
    # Test 1: Tavily domain inclusion
    captured_payload = {}

    class MockResponse:
        status_code = 200

        def json(self):
            return {
                "results": [
                    {
                        "title": "arXiv: Attention Is All You Need",
                        "url": "https://arxiv.org/abs/1706.03762",
                        "content": "Empirical Transformer research paper.",
                        "score": 0.99,
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
            nonlocal captured_payload
            captured_payload = json
            return MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    tavily_client = TavilySearchClient(api_key="mock-key")
    academic_results = await tavily_client.search("Transformers", focus_mode="academic")
    assert len(academic_results) == 1
    assert "arxiv.org" in captured_payload.get("include_domains", [])

    # Test 2: DuckDuckGo effective query enrichment
    captured_ddg_query = None

    class FakeDDGS:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def text(self, query, max_results=5):
            nonlocal captured_ddg_query
            captured_ddg_query = query
            return [{"title": "Tech Docs", "href": "https://github.com", "body": "Specs"}]

    try:
        monkeypatch.setattr("ddgs.DDGS", FakeDDGS)
    except Exception:
        pass
    try:
        monkeypatch.setattr("duckduckgo_search.DDGS", FakeDDGS)
    except Exception:
        pass

    ddg_client = DuckDuckGoSearchClient()
    await ddg_client.search("LangGraph internals", focus_mode="technical")
    assert captured_ddg_query is not None
    assert "site:github.com" in captured_ddg_query or "architecture" in captured_ddg_query
