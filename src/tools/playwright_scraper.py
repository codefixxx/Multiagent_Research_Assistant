"""Headless Playwright stealth browser client for Tier 3 web scraping fallback."""

from src.config import settings
from src.core.logger import logger
from src.schemas.finding import ExtractionStatus
from src.tools.scraper import ScrapedDocument

CLOUDFLARE_INDICATORS = (
    "just a moment...",
    "attention required! | cloudflare",
    "cf-browser-verification",
    "checking your browser before accessing",
    "ddos-guard",
    "security check to continue",
)


class PlaywrightScraperClient:
    """Headless Chromium browser scraper using playwright-stealth to bypass anti-bot and render dynamic SPAs."""

    def __init__(
        self,
        timeout: float | None = None,
        max_words: int | None = None,
        headless: bool | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.timeout = timeout or settings.PLAYWRIGHT_TIMEOUT_SECONDS
        self.max_words = max_words or settings.SCRAPER_MAX_WORDS_PER_PAGE
        self.headless = headless if headless is not None else settings.PLAYWRIGHT_HEADLESS
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        )

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

    def _is_cloudflare_challenge(self, title: str, html: str) -> bool:
        """Detect whether the returned page is a Cloudflare / anti-bot block challenge."""
        lowered_title = title.lower()
        if any(ind in lowered_title for ind in CLOUDFLARE_INDICATORS):
            return True
        lowered_html = html[:2000].lower()
        return any(ind in lowered_html for ind in CLOUDFLARE_INDICATORS)

    async def read_url(self, url: str) -> ScrapedDocument:
        """Fetch and render a URL in a headless stealth Chromium browser."""
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            return ScrapedDocument(
                url=url,
                status=ExtractionStatus.ERROR,
                error_message="Invalid HTTP/HTTPS URL scheme",
                tier="tier3_playwright",
            )

        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
            from playwright_stealth import Stealth
        except ImportError as e:
            logger.error("Playwright or playwright-stealth not installed", error=str(e))
            return ScrapedDocument(
                url=url,
                status=ExtractionStatus.ERROR,
                error_message="Playwright or playwright-stealth not installed in environment",
                tier="tier3_playwright",
            )

        timeout_ms = int(self.timeout * 1000)

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=self.headless,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                try:
                    context = await browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        user_agent=self.user_agent,
                        locale="en-US",
                        timezone_id="America/New_York",
                        extra_http_headers={
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                            "Accept-Language": "en-US,en;q=0.9",
                            "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
                            "Sec-Ch-Ua-Mobile": "?0",
                            "Sec-Ch-Ua-Platform": '"Windows"',
                            "Upgrade-Insecure-Requests": "1",
                        },
                    )
                    page = await context.new_page()

                    stealth = Stealth()
                    await stealth.apply_stealth_async(page)

                    response = await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=timeout_ms,
                    )

                    # Wait briefly for dynamic client-side hydration (SPAs)
                    try:
                        await page.wait_for_load_state(
                            "networkidle",
                            timeout=min(3000, max(500, timeout_ms / 3)),
                        )
                    except Exception:
                        pass  # Lingering network connections are expected on dynamic websites

                    title = (await page.title()).strip() or "Untitled Document"
                    html = await page.content()

                    status_code = response.status if response else 200

                    if self._is_cloudflare_challenge(title, html) or status_code in (401, 403):
                        logger.warning(
                            "Playwright encountered anti-bot block page",
                            url=url,
                            title=title,
                            status=status_code,
                        )
                        return ScrapedDocument(
                            url=url,
                            title=title,
                            status=ExtractionStatus.BLOCKED,
                            error_message=f"Anti-bot or CAPTCHA challenge detected (HTTP {status_code})",
                            tier="tier3_playwright",
                        )

                    # Extract clean main text using trafilatura
                    import trafilatura

                    extracted_text = trafilatura.extract(
                        html,
                        include_links=False,
                        include_comments=False,
                        output_format="txt",
                    )

                    # Fallback to in-browser DOM text extraction for JS SPAs where trafilatura finds no main article
                    if not extracted_text or not extracted_text.strip():
                        extracted_text = await page.evaluate("""() => {
                            const scripts = document.querySelectorAll('script, style, noscript, nav, footer, header');
                            scripts.forEach(s => s.remove());
                            return document.body ? (document.body.innerText || '') : '';
                        }""")

                    if not extracted_text or not extracted_text.strip():
                        return ScrapedDocument(
                            url=url,
                            title=title,
                            status=ExtractionStatus.NO_RESULTS,
                            error_message="No readable text rendered by page in Playwright",
                            tier="tier3_playwright",
                        )

                    clean_text, word_count = self._truncate_content(extracted_text)

                    logger.info(
                        "Playwright rendered page successfully",
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
                        tier="tier3_playwright",
                    )
                finally:
                    await browser.close()

        except PlaywrightTimeoutError:
            logger.warning("Playwright timed out fetching URL", url=url, timeout=self.timeout)
            return ScrapedDocument(
                url=url,
                status=ExtractionStatus.TIMED_OUT,
                error_message=f"Playwright navigation timed out after {self.timeout:.1f}s",
                tier="tier3_playwright",
            )
        except Exception as e:
            logger.warning("Playwright execution failed", url=url, error=str(e))
            return ScrapedDocument(
                url=url,
                status=ExtractionStatus.ERROR,
                error_message=f"Playwright error: {e}",
                tier="tier3_playwright",
            )
