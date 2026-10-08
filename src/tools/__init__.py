"""Web search, scraping, domain diversity, and evidence provenance tools."""

from src.tools.domain_guard import DomainDiversityGuard, canonicalize_url, extract_domain
from src.tools.errors import (
    ScraperError,
    SearchError,
    ToolError,
    map_http_status_to_extraction_status,
)
from src.tools.evidence_collector import EvidenceCollectionResult, EvidenceCollector
from src.tools.hacker_news import HackerNewsClient, HackerNewsStory
from src.tools.jina_reader import JinaReaderClient
from src.tools.scraper import DeepPageScraper, ScrapedDocument
from src.tools.search import (
    BaseSearchEngine,
    DuckDuckGoSearchClient,
    MockSearchClient,
    MultiSearchClient,
    SearchResult,
    TavilySearchClient,
)

__all__ = [
    "BaseSearchEngine",
    "DeepPageScraper",
    "DomainDiversityGuard",
    "DuckDuckGoSearchClient",
    "EvidenceCollectionResult",
    "EvidenceCollector",
    "HackerNewsClient",
    "HackerNewsStory",
    "JinaReaderClient",
    "MockSearchClient",
    "MultiSearchClient",
    "ScrapedDocument",
    "ScraperError",
    "SearchResult",
    "SearchError",
    "TavilySearchClient",
    "ToolError",
    "canonicalize_url",
    "extract_domain",
    "map_http_status_to_extraction_status",
]
