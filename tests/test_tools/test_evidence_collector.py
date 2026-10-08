"""Unit tests for the EvidenceCollector orchestrator."""

import pytest

from src.schemas.finding import ExtractionStatus
from src.tools.domain_guard import DomainDiversityGuard
from src.tools.evidence_collector import EvidenceCollector
from src.tools.scraper import DeepPageScraper, ScrapedDocument
from src.tools.search import MockSearchClient, MultiSearchClient, SearchResult


class StubSearchEngine(MockSearchClient):
    def __init__(self, results: list[SearchResult]) -> None:
        super().__init__(predefined_results=results)


class StubScraper(DeepPageScraper):
    def __init__(self, doc_mapping: dict[str, ScrapedDocument]) -> None:
        super().__init__()
        self.doc_mapping = doc_mapping

    async def scrape_page(self, url: str) -> ScrapedDocument:
        return self.doc_mapping.get(
            url,
            ScrapedDocument(
                url=url,
                status=ExtractionStatus.ERROR,
                error_message="Not found in stub",
            ),
        )

    async def scrape_multiple(
        self, urls: list[str], max_concurrency: int = 5
    ) -> list[ScrapedDocument]:
        return [await self.scrape_page(u) for u in urls]


@pytest.mark.asyncio
async def test_evidence_collector_happy_path():
    search_results = [
        SearchResult(
            title="Redis Persistence Details",
            url="https://redis.io/topics/persistence",
            snippet="Redis provides AOF and RDB snapshotting options.",
            engine="stub",
        ),
        SearchResult(
            title="Memcached Volatility Analysis",
            url="https://memcached.org/faq",
            snippet="Memcached is purely in-memory with zero persistence.",
            engine="stub",
        ),
    ]

    doc_mapping = {
        "https://redis.io/topics/persistence": ScrapedDocument(
            url="https://redis.io/topics/persistence",
            title="Redis Persistence Details",
            raw_text="Full deep page text: RDB creates point-in-time snapshots while AOF logs write operations.",
            status=ExtractionStatus.SUCCESS,
            word_count=13,
        ),
        "https://memcached.org/faq": ScrapedDocument(
            url="https://memcached.org/faq",
            title="Memcached Volatility Analysis",
            raw_text="Full deep page text: Memcached does not write data to disk.",
            status=ExtractionStatus.SUCCESS,
            word_count=10,
        ),
    }

    collector = EvidenceCollector(
        search_client=MultiSearchClient(mock_client=StubSearchEngine(search_results)),
        scraper=StubScraper(doc_mapping),
        domain_guard=DomainDiversityGuard(max_per_domain=2),
    )

    result = await collector.collect_evidence_for_queries(
        queries=["Redis vs Memcached persistence"],
        deep_scrape=True,
    )

    assert result.status == ExtractionStatus.SUCCESS
    assert len(result.documents) == 2
    assert "https://redis.io/topics/persistence" in result.formatted_context
    assert "https://memcached.org/faq" in result.formatted_context
    assert "RDB creates point-in-time snapshots" in result.formatted_context
    assert "Deep Webpage Content" in result.formatted_context


@pytest.mark.asyncio
async def test_evidence_collector_no_results():
    collector = EvidenceCollector(
        search_client=MultiSearchClient(mock_client=StubSearchEngine([])),
        scraper=StubScraper({}),
    )

    result = await collector.collect_evidence_for_queries(
        queries=["Non-existent technical keyword 123456"],
    )

    assert result.status == ExtractionStatus.NO_RESULTS
    assert "No web search results were found" in result.formatted_context
    assert len(result.documents) == 0


@pytest.mark.asyncio
async def test_evidence_collector_snippet_fallback_on_scrape_failure():
    search_results = [
        SearchResult(
            title="Paywalled Benchmark Site",
            url="https://paywalled.com/benchmarks",
            snippet="Preview snippet: Memcached handles 1M ops/sec with 16 worker threads.",
            engine="stub",
        )
    ]

    # Scraper fails with BLOCKED
    doc_mapping = {
        "https://paywalled.com/benchmarks": ScrapedDocument(
            url="https://paywalled.com/benchmarks",
            status=ExtractionStatus.BLOCKED,
            error_message="HTTP 403 Forbidden",
        )
    }

    collector = EvidenceCollector(
        search_client=MultiSearchClient(mock_client=StubSearchEngine(search_results)),
        scraper=StubScraper(doc_mapping),
    )

    result = await collector.collect_evidence_for_queries(
        queries=["Multithreading throughput"],
        deep_scrape=True,
    )

    assert result.status == ExtractionStatus.SUCCESS
    # Verified it fell back to snippet
    assert "Search Engine Snippet" in result.formatted_context
    assert "Memcached handles 1M ops/sec" in result.formatted_context
