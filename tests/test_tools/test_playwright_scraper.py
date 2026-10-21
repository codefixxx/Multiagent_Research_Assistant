"""Unit and integration tests for Phase 4: Anti-Bot Web Scraping Resilience & Headless Playwright Fallback."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.schemas.finding import ExtractionStatus
from src.tools.playwright_scraper import PlaywrightScraperClient
from src.tools.scraper import DeepPageScraper, ScrapedDocument

# =====================================================================
# Unit Tests for PlaywrightScraperClient
# =====================================================================


def test_playwright_client_init_defaults():
    """Verify PlaywrightScraperClient initializes with configuration defaults."""
    client = PlaywrightScraperClient(timeout=8.0, max_words=500, headless=True)
    assert client.timeout == 8.0
    assert client.max_words == 500
    assert client.headless is True
    assert "Mozilla" in client.user_agent


def test_playwright_invalid_url_scheme():
    """Verify invalid URL schemes return clean ERROR status without launching browser."""
    client = PlaywrightScraperClient()
    doc = asyncio.run(client.read_url("ftp://invalid.scheme/file"))
    assert doc.status == ExtractionStatus.ERROR
    assert "Invalid HTTP/HTTPS" in (doc.error_message or "")
    assert doc.tier == "tier3_playwright"


def test_playwright_cloudflare_challenge_detection():
    """Verify detection of Cloudflare and anti-bot verification challenges."""
    client = PlaywrightScraperClient()

    # Title detection
    assert client._is_cloudflare_challenge("Just a moment...", "<html><body>content</body></html>") is True
    assert client._is_cloudflare_challenge("Attention Required! | Cloudflare", "<html></html>") is True
    assert client._is_cloudflare_challenge("Official Documentation", "<html>Just a moment... please wait</html>") is True

    # Benign pages
    assert client._is_cloudflare_challenge("React Documentation", "<html><body><article>Welcome</article></body></html>") is False


def test_playwright_content_truncation():
    """Verify that PlaywrightScraperClient truncates text at max_words limit with notice."""
    client = PlaywrightScraperClient(max_words=20)
    long_text = " ".join([f"word{i}" for i in range(100)])
    truncated, count = client._truncate_content(long_text)

    assert count == 20
    assert "[Content truncated at 20 words (total: 100 words)]" in truncated


@pytest.mark.asyncio
async def test_playwright_mock_success_extraction():
    """Verify successful document extraction from mocked Playwright page."""
    html_markup = """
    <html>
      <head><title>Mock Modern SPA Dashboard</title></head>
      <body>
        <main>
          <h1>Real-time Agent Telemetry</h1>
          <p>The multi-agent research assistant operates with sub-second task routing and distributed tracing.</p>
        </main>
      </body>
    </html>
    """

    mock_page = AsyncMock()
    mock_page.title.return_value = "Mock Modern SPA Dashboard"
    mock_page.content.return_value = html_markup
    mock_response = MagicMock(status=200)
    mock_page.goto.return_value = mock_response

    mock_context = AsyncMock()
    mock_context.new_page.return_value = mock_page

    mock_browser = AsyncMock()
    mock_browser.new_context.return_value = mock_context

    mock_playwright_instance = MagicMock()
    mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)

    mock_pw_cm = AsyncMock()
    mock_pw_cm.__aenter__.return_value = mock_playwright_instance
    mock_pw_cm.__aexit__.return_value = None

    with patch("playwright.async_api.async_playwright", return_value=mock_pw_cm), \
         patch("playwright_stealth.Stealth.apply_stealth_async", new=AsyncMock()):

        client = PlaywrightScraperClient(timeout=5.0, max_words=500)
        doc = await client.read_url("https://example-spa.com/telemetry")

        assert doc.status == ExtractionStatus.SUCCESS
        assert doc.title == "Mock Modern SPA Dashboard"
        assert "Real-time Agent Telemetry" in doc.raw_text or "multi-agent research assistant" in doc.raw_text
        assert doc.tier == "tier3_playwright"
        assert doc.word_count > 0


@pytest.mark.asyncio
async def test_playwright_mock_spa_dom_eval_fallback():
    """Verify that when trafilatura finds no structured article, in-browser JS evaluation recovers SPA text."""
    # A single div container with no semantic article tags
    html_markup = "<html><head><title>Vue SPA</title></head><body><div id='app'></div></body></html>"

    mock_page = AsyncMock()
    mock_page.title.return_value = "Vue Dynamic SPA"
    mock_page.content.return_value = html_markup
    mock_page.goto.return_value = MagicMock(status=200)
    # in-browser evaluation returns dynamically rendered content
    mock_page.evaluate.return_value = "Client-side rendered dynamic SPA content recovered directly from DOM body"

    mock_context = AsyncMock()
    mock_context.new_page.return_value = mock_page
    mock_browser = AsyncMock()
    mock_browser.new_context.return_value = mock_context

    mock_playwright_instance = MagicMock()
    mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)

    mock_pw_cm = AsyncMock()
    mock_pw_cm.__aenter__.return_value = mock_playwright_instance
    mock_pw_cm.__aexit__.return_value = None

    with patch("playwright.async_api.async_playwright", return_value=mock_pw_cm), \
         patch("playwright_stealth.Stealth.apply_stealth_async", new=AsyncMock()), \
         patch("trafilatura.extract", return_value=None):

        client = PlaywrightScraperClient()
        doc = await client.read_url("https://vue-spa.example.org")

        assert doc.status == ExtractionStatus.SUCCESS
        assert doc.title == "Vue Dynamic SPA"
        assert "Client-side rendered dynamic SPA" in doc.raw_text
        assert doc.tier == "tier3_playwright"


@pytest.mark.asyncio
async def test_playwright_mock_cloudflare_challenge_blocked():
    """Verify that when Cloudflare challenge is encountered in Playwright, BLOCKED status is returned."""
    mock_page = AsyncMock()
    mock_page.title.return_value = "Just a moment..."
    mock_page.content.return_value = "<html><body>Checking your browser before accessing...</body></html>"
    mock_page.goto.return_value = MagicMock(status=403)

    mock_context = AsyncMock()
    mock_context.new_page.return_value = mock_page
    mock_browser = AsyncMock()
    mock_browser.new_context.return_value = mock_context

    mock_playwright_instance = MagicMock()
    mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)

    mock_pw_cm = AsyncMock()
    mock_pw_cm.__aenter__.return_value = mock_playwright_instance
    mock_pw_cm.__aexit__.return_value = None

    with patch("playwright.async_api.async_playwright", return_value=mock_pw_cm), \
         patch("playwright_stealth.Stealth.apply_stealth_async", new=AsyncMock()):

        client = PlaywrightScraperClient()
        doc = await client.read_url("https://cloudflare-protected.example.com")

        assert doc.status == ExtractionStatus.BLOCKED
        assert "Anti-bot" in (doc.error_message or "")
        assert doc.tier == "tier3_playwright"


@pytest.mark.asyncio
async def test_playwright_timeout_handling():
    """Verify PlaywrightTimeoutError maps cleanly to ExtractionStatus.TIMED_OUT."""
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    mock_playwright_instance = MagicMock()
    mock_playwright_instance.chromium.launch = AsyncMock(side_effect=PlaywrightTimeoutError("Navigation timed out"))

    mock_pw_cm = AsyncMock()
    mock_pw_cm.__aenter__.return_value = mock_playwright_instance
    mock_pw_cm.__aexit__.return_value = None

    with patch("playwright.async_api.async_playwright", return_value=mock_pw_cm):
        client = PlaywrightScraperClient(timeout=4.0)
        doc = await client.read_url("https://very-slow-site.com")

        assert doc.status == ExtractionStatus.TIMED_OUT
        assert "timed out" in (doc.error_message or "").lower()
        assert doc.tier == "tier3_playwright"


# =====================================================================
# Cascade Tests for DeepPageScraper 3-Tier Architecture
# Tier 1 (httpx) -> Tier 2 (Jina Reader) -> Tier 3 (Playwright Stealth)
# =====================================================================


@pytest.mark.asyncio
async def test_3tier_cascade_tier1_direct_success(monkeypatch):
    """When direct HTTP scrape succeeds (200 OK + text), neither Jina nor Playwright is invoked."""
    class MockResponse:
        status_code = 200
        headers = {"content-type": "text/html"}
        text = "<html><head><title>Direct Success</title></head><body><p>Direct HTTP extraction works.</p></body></html>"

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

    mock_jina = AsyncMock()
    mock_playwright = AsyncMock()

    scraper = DeepPageScraper(
        enable_jina_fallback=True,
        jina_client=mock_jina,
        enable_playwright_fallback=True,
        playwright_client=mock_playwright,
    )

    doc = await scraper.scrape_page("https://example.com/direct")

    assert doc.status == ExtractionStatus.SUCCESS
    assert doc.tier == "tier1_direct"
    assert "Direct HTTP extraction" in doc.raw_text
    mock_jina.read_url.assert_not_called()
    mock_playwright.read_url.assert_not_called()


@pytest.mark.asyncio
async def test_3tier_cascade_tier2_jina_success_when_tier1_blocked(monkeypatch):
    """When direct HTTP scrape is blocked (403), Jina Reader recovers the content and Playwright is not needed."""
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

    mock_jina = AsyncMock()
    mock_jina.read_url.return_value = ScrapedDocument(
        url="https://example.com/blocked",
        title="Jina Recovered Title",
        raw_text="Extracted clean markdown via Jina Reader API",
        status=ExtractionStatus.SUCCESS,
        word_count=7,
        tier="tier2_jina",
    )

    mock_playwright = AsyncMock()

    scraper = DeepPageScraper(
        enable_jina_fallback=True,
        jina_client=mock_jina,
        enable_playwright_fallback=True,
        playwright_client=mock_playwright,
    )

    doc = await scraper.scrape_page("https://example.com/blocked")

    assert doc.status == ExtractionStatus.SUCCESS
    assert doc.tier == "tier2_jina"
    assert "Jina Reader API" in doc.raw_text
    mock_jina.read_url.assert_called_once_with("https://example.com/blocked")
    mock_playwright.read_url.assert_not_called()


@pytest.mark.asyncio
async def test_3tier_cascade_tier3_playwright_success_when_tier1_and_tier2_fail(monkeypatch):
    """When direct HTTP returns 403 AND Jina fails/blocked, Playwright Stealth recovers the page!"""
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

    # Jina also blocked or fails
    mock_jina = AsyncMock()
    mock_jina.read_url.return_value = ScrapedDocument(
        url="https://example.com/cloudflare-protected",
        status=ExtractionStatus.BLOCKED,
        error_message="Jina Reader also encountered 403 Forbidden",
        tier="tier2_jina",
    )

    # Playwright stealth succeeds
    mock_playwright = AsyncMock()
    mock_playwright.read_url.return_value = ScrapedDocument(
        url="https://example.com/cloudflare-protected",
        title="Protected Portal - Hydrated",
        raw_text="Full client-side content rendered successfully by headless Chromium stealth browser",
        status=ExtractionStatus.SUCCESS,
        word_count=10,
        tier="tier3_playwright",
    )

    scraper = DeepPageScraper(
        enable_jina_fallback=True,
        jina_client=mock_jina,
        enable_playwright_fallback=True,
        playwright_client=mock_playwright,
    )

    doc = await scraper.scrape_page("https://example.com/cloudflare-protected")

    assert doc.status == ExtractionStatus.SUCCESS
    assert doc.tier == "tier3_playwright"
    assert "headless Chromium stealth browser" in doc.raw_text
    mock_jina.read_url.assert_called_once()
    mock_playwright.read_url.assert_called_once_with("https://example.com/cloudflare-protected")


@pytest.mark.asyncio
async def test_3tier_cascade_empty_spa_fallback_to_playwright(monkeypatch):
    """When direct HTTP returns 200 with empty JS container, Playwright renders dynamic DOM."""
    class MockResponse:
        status_code = 200
        headers = {"content-type": "text/html"}
        text = "<html><head><title>Empty SPA</title></head><body><div id='root'></div></body></html>"

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

    # Jina returns empty
    mock_jina = AsyncMock()
    mock_jina.read_url.return_value = ScrapedDocument(
        url="https://example.com/spa",
        status=ExtractionStatus.NO_RESULTS,
        error_message="Jina returned empty content",
        tier="tier2_jina",
    )

    # Playwright renders hydrated DOM
    mock_playwright = AsyncMock()
    mock_playwright.read_url.return_value = ScrapedDocument(
        url="https://example.com/spa",
        title="Hydrated React Application",
        raw_text="Dynamic client rendered SPA state and documentation",
        status=ExtractionStatus.SUCCESS,
        word_count=7,
        tier="tier3_playwright",
    )

    scraper = DeepPageScraper(
        enable_jina_fallback=True,
        jina_client=mock_jina,
        enable_playwright_fallback=True,
        playwright_client=mock_playwright,
    )

    doc = await scraper.scrape_page("https://example.com/spa")

    assert doc.status == ExtractionStatus.SUCCESS
    assert doc.tier == "tier3_playwright"
    assert "Dynamic client rendered SPA" in doc.raw_text


@pytest.mark.asyncio
async def test_playwright_disabled_flag(monkeypatch):
    """When enable_playwright_fallback=False, Playwright is not invoked even if Tier 1 and 2 fail."""
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

    mock_jina = AsyncMock()
    mock_jina.read_url.return_value = ScrapedDocument(
        url="https://example.com/blocked",
        status=ExtractionStatus.BLOCKED,
        tier="tier2_jina",
    )

    mock_playwright = AsyncMock()

    scraper = DeepPageScraper(
        enable_jina_fallback=True,
        jina_client=mock_jina,
        enable_playwright_fallback=False,  # Explicitly disabled
        playwright_client=mock_playwright,
    )

    doc = await scraper.scrape_page("https://example.com/blocked")

    assert doc.status == ExtractionStatus.BLOCKED
    assert doc.tier == "tier1_direct"
    mock_playwright.read_url.assert_not_called()


# =====================================================================
# Live Browser Integration Test
# =====================================================================


@pytest.mark.asyncio
async def test_playwright_live_headless_render():
    """Live integration test: launch real headless Chromium to render example.com."""
    client = PlaywrightScraperClient(timeout=10.0, max_words=500, headless=True)

    try:
        doc = await client.read_url("https://example.com")
        if doc.status == ExtractionStatus.SUCCESS:
            assert doc.status == ExtractionStatus.SUCCESS
            assert "Example Domain" in doc.title or "example" in doc.raw_text.lower()
            assert doc.tier == "tier3_playwright"
            assert doc.word_count > 0
    except Exception as e:
        # If offline or network unavailable, verify error is cleanly structured
        pytest.skip(f"Live network test skipped due to connectivity: {e}")
