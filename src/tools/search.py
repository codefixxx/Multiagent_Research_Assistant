"""Production Search Tool with Tavily API primary and DuckDuckGo fallback."""

import asyncio
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import BaseModel, Field

from src.config import settings
from src.core.logger import logger
from src.schemas.finding import ExtractionStatus
from src.tools.errors import SearchError


class SearchResult(BaseModel):
    """Normalized structured search engine result."""

    title: str = Field(description="Webpage title.")
    url: str = Field(description="Destination URL.")
    snippet: str = Field(description="Text excerpt or search engine snippet.")
    score: float | None = Field(default=None, description="Search relevance score if provided.")
    engine: str = Field(default="unknown", description="Search provider that yielded this result.")
    raw_content: str | None = Field(
        default=None,
        description="Full markdown/text content if returned by the search provider.",
    )


class BaseSearchEngine(ABC):
    """Abstract interface for web search engine clients."""

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Execute web search query asynchronously."""
        ...


class TavilySearchClient(BaseSearchEngine):
    """Search client utilizing the Tavily Search REST API."""

    ENDPOINT = "https://api.tavily.com/search"

    def __init__(self, api_key: str | None = None, timeout: float = 10.0) -> None:
        self.api_key = api_key or settings.TAVILY_API_KEY
        self.timeout = timeout

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if not self.api_key:
            raise SearchError("Tavily API key is not configured.", status=ExtractionStatus.ERROR)

        payload: dict[str, Any] = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_raw_content": False,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.ENDPOINT, json=payload)

            if response.status_code == 429:
                raise SearchError(
                    "Tavily API rate limit exceeded",
                    status=ExtractionStatus.RATE_LIMITED,
                )
            if response.status_code != 200:
                raise SearchError(
                    f"Tavily API returned HTTP {response.status_code}: {response.text[:200]}",
                    status=ExtractionStatus.ERROR,
                )

            data = response.json()
            raw_results = data.get("results", [])

            results: list[SearchResult] = []
            for item in raw_results:
                results.append(
                    SearchResult(
                        title=item.get("title", "Untitled"),
                        url=item.get("url", ""),
                        snippet=item.get("content", ""),
                        score=item.get("score"),
                        engine="tavily",
                        raw_content=item.get("raw_content"),
                    )
                )

            logger.info("Tavily search completed", query=query, results_count=len(results))
            return results

        except httpx.TimeoutException as e:
            raise SearchError(
                f"Tavily search timed out: {e}", status=ExtractionStatus.TIMED_OUT
            ) from e
        except SearchError:
            raise
        except Exception as e:
            raise SearchError(f"Tavily search failed: {e}", status=ExtractionStatus.ERROR) from e


class DuckDuckGoSearchClient(BaseSearchEngine):
    """Fallback search client utilizing DuckDuckGo without requiring API keys."""

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS  # type: ignore[no-redef]

            def _sync_ddg_search() -> list[dict[str, Any]]:
                with DDGS(timeout=int(self.timeout)) as ddgs:
                    return list(ddgs.text(query, max_results=max_results))

            raw_results = await asyncio.to_thread(_sync_ddg_search)

            results: list[SearchResult] = []
            for item in raw_results:
                results.append(
                    SearchResult(
                        title=item.get("title", "Untitled"),
                        url=item.get("href") or item.get("url") or "",
                        snippet=item.get("body") or item.get("snippet") or "",
                        score=None,
                        engine="duckduckgo",
                    )
                )

            logger.info("DuckDuckGo search completed", query=query, results_count=len(results))
            return results

        except Exception as e:
            err_msg = str(e).lower()
            if "ratelimit" in err_msg or "202" in err_msg or "429" in err_msg:
                status = ExtractionStatus.RATE_LIMITED
            else:
                status = ExtractionStatus.ERROR
            raise SearchError(f"DuckDuckGo search failed: {e}", status=status) from e


class MockSearchClient(BaseSearchEngine):
    """Deterministic synthetic search client for unit testing and offline development."""

    def __init__(self, predefined_results: list[SearchResult] | None = None) -> None:
        self.predefined_results = predefined_results

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if self.predefined_results is not None:
            return self.predefined_results[:max_results]

        # Generate realistic synthetic results
        results = [
            SearchResult(
                title=f"Technical Overview: {query}",
                url=f"https://example.com/research/{abs(hash(query)) % 1000}",
                snippet=f"Detailed analysis regarding '{query}'. Key benchmarks demonstrate low latency and high reliability.",
                score=0.95,
                engine="mock",
            ),
            SearchResult(
                title=f"Architectural Comparison for {query}",
                url=f"https://docs.example.org/arch/{abs(hash(query)) % 500}",
                snippet=f"Comprehensive documentation comparing operational trade-offs for '{query}'.",
                score=0.88,
                engine="mock",
            ),
        ]
        return results[:max_results]


class MultiSearchClient:
    """Unified search client managing engine selection, fallback, and status tracking."""

    def __init__(
        self,
        tavily_client: BaseSearchEngine | None = None,
        ddg_client: BaseSearchEngine | None = None,
        mock_client: BaseSearchEngine | None = None,
    ) -> None:
        self.tavily = tavily_client or TavilySearchClient()
        self.ddg = ddg_client or DuckDuckGoSearchClient()
        self.mock = mock_client

    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> tuple[list[SearchResult], ExtractionStatus]:
        """Execute a search with automatic provider fallback.

        Returns:
            Tuple of (list of SearchResult, ExtractionStatus).
        """
        # 0. Injected mock client takes absolute priority (for test isolation)
        if self.mock is not None:
            results = await self.mock.search(query, max_results=max_results)
            status = ExtractionStatus.SUCCESS if results else ExtractionStatus.NO_RESULTS
            return results, status

        mode = settings.SEARCH_ENGINE.lower()

        # 1. Force Mock Mode if configured in settings
        if mode == "mock" or settings.LLM_PROVIDER == "mock":
            results = await MockSearchClient().search(query, max_results=max_results)
            status = ExtractionStatus.SUCCESS if results else ExtractionStatus.NO_RESULTS
            return results, status

        # 2. Force DuckDuckGo if requested
        if mode == "duckduckgo":
            try:
                results = await self.ddg.search(query, max_results=max_results)
                status = ExtractionStatus.SUCCESS if results else ExtractionStatus.NO_RESULTS
                return results, status
            except SearchError as e:
                logger.warning(
                    "DuckDuckGo search error", query=query, status=e.status, error=str(e)
                )
                return [], e.status

        # 3. Force Tavily if requested
        if mode == "tavily":
            try:
                results = await self.tavily.search(query, max_results=max_results)
                status = ExtractionStatus.SUCCESS if results else ExtractionStatus.NO_RESULTS
                return results, status
            except SearchError as e:
                logger.warning("Tavily search error", query=query, status=e.status, error=str(e))
                return [], e.status

        # 4. Auto mode: Try Tavily first if key is provided, fallback to DuckDuckGo
        if settings.TAVILY_API_KEY:
            try:
                results = await self.tavily.search(query, max_results=max_results)
                if results:
                    return results, ExtractionStatus.SUCCESS
            except SearchError as e:
                logger.warning(
                    "Tavily search failed; falling back to DuckDuckGo",
                    query=query,
                    error=str(e),
                )

        # Fallback to DuckDuckGo
        try:
            results = await self.ddg.search(query, max_results=max_results)
            status = ExtractionStatus.SUCCESS if results else ExtractionStatus.NO_RESULTS
            return results, status
        except SearchError as e:
            logger.warning("DuckDuckGo fallback search also failed", query=query, error=str(e))
            return [], e.status
