"""Canonical URL deduplication and domain diversity guardrails."""

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from src.core.logger import logger

# Tracking query parameters to strip during canonicalization
TRACKING_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "gclsrc",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "_hsenc",
    "_hsmi",
    "ref",
    "ref_src",
    "source",
}


def canonicalize_url(url: str) -> str:
    """Normalize and canonicalize a URL for reliable deduplication.

    Actions performed:
    1. Lowercase scheme and host.
    2. Remove default ports (80 for http, 443 for https).
    3. Strip tracking query parameters (e.g. utm_*, fbclid, gclid).
    4. Strip URL fragment (#...).
    5. Strip trailing slash from path (unless path is empty or single slash).
    6. Sort remaining query parameters deterministically.
    """
    if not url or not url.strip():
        return ""

    try:
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            return url.strip()

        # Normalize netloc (lowercase, strip port if default)
        netloc = parsed.netloc.lower()
        if netloc.endswith(":80") and scheme == "http":
            netloc = netloc[:-3]
        elif netloc.endswith(":443") and scheme == "https":
            netloc = netloc[:-4]

        # Normalize path
        path = parsed.path
        if path.endswith("/") and len(path) > 1:
            path = path.rstrip("/")

        # Filter out tracking query params and sort remainder
        query_params = parse_qsl(parsed.query, keep_blank_values=True)
        filtered_params = [
            (k, v)
            for k, v in query_params
            if k.lower() not in TRACKING_QUERY_PARAMS and not k.lower().startswith("utm_")
        ]
        filtered_params.sort(key=lambda item: item[0])
        clean_query = urlencode(filtered_params)

        # No fragments in canonical representation
        return urlunparse((scheme, netloc, path, parsed.params, clean_query, ""))
    except Exception as e:
        logger.debug("Failed to canonicalize URL; returning original", url=url, error=str(e))
        return url.strip()


def extract_domain(url: str) -> str:
    """Extract clean domain/host name from a URL, stripping leading www."""
    try:
        parsed = urlparse(url.strip())
        host = (parsed.netloc or parsed.path).lower().split(":")[0]
        return re.sub(r"^www\.", "", host)
    except Exception:
        return ""


class DomainDiversityGuard:
    """Guards against duplicate URLs and over-representation of single domains.

    Enforces:
    1. Exact URL deduplication based on canonical URLs.
    2. Domain bias ceiling: max citations/scrapes allowed per domain per report run.
    """

    def __init__(self, max_per_domain: int = 2) -> None:
        self.max_per_domain = max_per_domain
        self.seen_canonical_urls: set[str] = set()
        self.domain_counts: dict[str, int] = {}

    def is_allowed(self, url: str) -> bool:
        """Check if a URL is permitted under canonical uniqueness and domain cap rules."""
        canonical = canonicalize_url(url)
        if not canonical:
            return False

        if canonical in self.seen_canonical_urls:
            return False

        domain = extract_domain(canonical)
        if not domain:
            return False

        count = self.domain_counts.get(domain, 0)
        return count < self.max_per_domain

    def record_url(self, url: str) -> bool:
        """Attempt to record a URL.

        Returns True if URL was accepted and recorded, or False if rejected.
        """
        canonical = canonicalize_url(url)
        if not canonical or canonical in self.seen_canonical_urls:
            return False

        domain = extract_domain(canonical)
        if not domain:
            return False

        current_count = self.domain_counts.get(domain, 0)
        if current_count >= self.max_per_domain:
            logger.debug(
                "Domain cap reached; rejecting URL",
                domain=domain,
                limit=self.max_per_domain,
                url=url,
            )
            return False

        self.seen_canonical_urls.add(canonical)
        self.domain_counts[domain] = current_count + 1
        return True

    def filter_urls(self, urls: list[str]) -> list[str]:
        """Filter a list of URLs, retaining only allowed URLs and updating guard state."""
        allowed: list[str] = []
        for url in urls:
            if self.record_url(url):
                allowed.append(url)
        return allowed

    def get_domain_count(self, domain: str) -> int:
        """Get the number of times a domain has been recorded."""
        clean = re.sub(r"^www\.", "", domain.lower().strip())
        return self.domain_counts.get(clean, 0)

    def reset(self) -> None:
        """Reset seen URLs and domain frequency tracking."""
        self.seen_canonical_urls.clear()
        self.domain_counts.clear()
