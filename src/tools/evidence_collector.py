"""Evidence Collector coordinating search, domain diversity, deep scraping, and provenance."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from src.config import settings
from src.core.logger import logger
from src.schemas.finding import ExtractionStatus
from src.tools.domain_guard import DomainDiversityGuard
from src.tools.scraper import DeepPageScraper, ScrapedDocument
from src.tools.search import BaseSearchEngine, MultiSearchClient, SearchResult


class EvidenceCollectionResult(BaseModel):
    """Result of an evidence gathering pass across search and web scraping."""

    formatted_context: str = Field(
        description="Formatted markdown context with complete provenance."
    )
    documents: list[ScrapedDocument] = Field(default_factory=list)
    search_results: list[SearchResult] = Field(default_factory=list)
    status: ExtractionStatus = Field(default=ExtractionStatus.SUCCESS)
    queries_executed: list[str] = Field(default_factory=list)
    urls_processed: list[str] = Field(default_factory=list)


class EvidenceCollector:
    """Orchestrates search, URL filtering, deep page scraping, and evidence compilation."""

    def __init__(
        self,
        search_client: MultiSearchClient | BaseSearchEngine | None = None,
        scraper: DeepPageScraper | None = None,
        domain_guard: DomainDiversityGuard | None = None,
        hn_client: Any = None,
        enable_hacker_news: bool | None = None,
    ) -> None:
        self.search_client = search_client or MultiSearchClient()
        self.scraper = scraper or DeepPageScraper()
        self.domain_guard = domain_guard or DomainDiversityGuard(
            max_per_domain=settings.MAX_CITATIONS_PER_DOMAIN
        )
        self.enable_hn = (
            enable_hacker_news
            if enable_hacker_news is not None
            else settings.ENABLE_HACKER_NEWS
        )
        self.hn_client = hn_client

    async def collect_evidence_for_queries(
        self,
        queries: list[str],
        max_results_per_query: int | None = None,
        deep_scrape: bool = True,
        max_pages_to_scrape: int = 5,
    ) -> EvidenceCollectionResult:
        """Execute searches across queries, scrape allowed URLs, and assemble provenance context."""
        limit = max_results_per_query or settings.SEARCH_MAX_RESULTS_PER_QUERY
        all_search_results: list[SearchResult] = []
        collected_urls: list[str] = []
        overall_status = ExtractionStatus.SUCCESS

        # 1. Execute searches across all provided queries concurrently
        async def _search_query(q: str) -> tuple[list[SearchResult], ExtractionStatus]:
            res = await self.search_client.search(q, max_results=limit)
            if isinstance(res, tuple):
                return res
            return res, (ExtractionStatus.SUCCESS if res else ExtractionStatus.NO_RESULTS)

        search_tasks = [_search_query(q) for q in queries]
        search_outcomes = await asyncio.gather(*search_tasks, return_exceptions=True)

        for q, outcome in zip(queries, search_outcomes, strict=False):
            if isinstance(outcome, BaseException):
                logger.warning("Search query execution failed", query=q, error=str(outcome))
                continue
            res_list, status = outcome
            all_search_results.extend(res_list)
            if not res_list and status != ExtractionStatus.SUCCESS:
                overall_status = status

        if not all_search_results:
            logger.info("Evidence collector found no search results", queries=queries)
            return EvidenceCollectionResult(
                formatted_context="No web search results were found for the requested queries.",
                documents=[],
                search_results=[],
                status=overall_status
                if overall_status != ExtractionStatus.SUCCESS
                else ExtractionStatus.NO_RESULTS,
                queries_executed=queries,
                urls_processed=[],
            )

        # 2. Filter URLs with Domain Diversity Guard
        unique_urls_to_scrape: list[str] = []
        for result in all_search_results:
            if result.url and self.domain_guard.record_url(result.url):
                unique_urls_to_scrape.append(result.url)
                if len(unique_urls_to_scrape) >= max_pages_to_scrape:
                    break

        scraped_docs: list[ScrapedDocument] = []
        if deep_scrape and unique_urls_to_scrape:
            # 3. Deep scrape the allowed URLs concurrently
            scraped_docs = await self.scraper.scrape_multiple(unique_urls_to_scrape)
            collected_urls = unique_urls_to_scrape

        # 4. Build Evidence Markdown with Provenance
        doc_map = {doc.url: doc for doc in scraped_docs if doc.status == ExtractionStatus.SUCCESS}
        sections: list[str] = []
        item_num = 1
        retrieval_time = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Map URLs to their best content (deep scraped text preferred, snippet fallback)
        seen_urls_in_context: set[str] = set()

        for res in all_search_results:
            if res.url in seen_urls_in_context or not res.url:
                continue

            doc = doc_map.get(res.url)
            if doc and doc.raw_text.strip():
                content_text = doc.raw_text.strip()
                source_kind = "Deep Webpage Content"
                title = doc.title or res.title
            else:
                content_text = res.snippet.strip()
                source_kind = "Search Engine Snippet"
                title = res.title

            if not content_text:
                continue

            seen_urls_in_context.add(res.url)
            sections.append(
                f"### Evidence [{item_num}]: {title}\n"
                f"- **Source URL:** {res.url}\n"
                f"- **Source Type:** {source_kind} ({res.engine})\n"
                f"- **Retrieved At:** {retrieval_time}\n"
                f"- **Content Excerpt / Body:**\n"
                f"{content_text}\n"
            )
            item_num += 1

        formatted_context = (
            "\n---\n".join(sections) if sections else "No usable evidence content extracted."
        )

        # 5. Optionally query and append Hacker News developer community discussions
        if self.enable_hn and queries:
            try:
                from src.tools.hacker_news import HackerNewsClient

                hn = self.hn_client or HackerNewsClient()
                stories = await hn.search_discussions(queries[0])
                if stories:
                    hn_md = hn.format_for_evidence(stories)
                    if hn_md:
                        formatted_context += (
                            f"\n\n---\n## Real-World Developer Discussions (Hacker News)\n{hn_md}"
                        )
            except Exception as e:
                logger.debug("Hacker News fetch skipped", error=str(e))

        return EvidenceCollectionResult(
            formatted_context=formatted_context,
            documents=scraped_docs,
            search_results=all_search_results,
            status=ExtractionStatus.SUCCESS if (sections or self.enable_hn) else ExtractionStatus.NO_RESULTS,
            queries_executed=queries,
            urls_processed=collected_urls,
        )

