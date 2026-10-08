"""Unit tests for URL canonicalization and domain diversity guardrails."""

from src.tools.domain_guard import DomainDiversityGuard, canonicalize_url, extract_domain


def test_canonicalize_url_strips_tracking_params():
    url = (
        "https://example.com/blog/article?utm_source=twitter&utm_medium=social"
        "&fbclid=12345&utm_campaign=launch&topic=python"
    )
    clean = canonicalize_url(url)
    assert clean == "https://example.com/blog/article?topic=python"
    assert "utm_source" not in clean
    assert "fbclid" not in clean


def test_canonicalize_url_strips_fragments_and_ports():
    url = "HTTPS://WWW.EXAMPLE.COM:443/docs/overview/?ref=newsletter#heading-2"
    clean = canonicalize_url(url)
    assert clean == "https://www.example.com/docs/overview"
    assert "#heading-2" not in clean
    assert ":443" not in clean


def test_canonicalize_url_deterministic_query_ordering():
    url1 = "https://example.com/search?z=3&a=1&m=2"
    url2 = "https://example.com/search?a=1&m=2&z=3"
    assert canonicalize_url(url1) == canonicalize_url(url2)
    assert canonicalize_url(url1) == "https://example.com/search?a=1&m=2&z=3"


def test_extract_domain():
    assert extract_domain("https://www.redis.io/docs/latency") == "redis.io"
    assert extract_domain("http://github.com/langchain-ai") == "github.com"
    assert extract_domain("https://sub.domain.co.uk:8080/path") == "sub.domain.co.uk"


def test_domain_diversity_guard_deduplication():
    guard = DomainDiversityGuard(max_per_domain=2)

    url1 = "https://example.com/guide?utm_source=google"
    url2 = "https://example.com/guide?utm_medium=cpc"

    # First one allowed
    assert guard.is_allowed(url1) is True
    assert guard.record_url(url1) is True

    # Second one has the same canonical URL -> rejected as duplicate
    assert guard.is_allowed(url2) is False
    assert guard.record_url(url2) is False


def test_domain_diversity_guard_max_per_domain_ceiling():
    guard = DomainDiversityGuard(max_per_domain=2)

    doc1 = "https://redis.io/topics/persistence"
    doc2 = "https://redis.io/topics/memory-optimization"
    doc3 = "https://redis.io/topics/cluster-tutorial"
    doc_other = "https://memcached.org/about"

    assert guard.record_url(doc1) is True
    assert guard.record_url(doc2) is True
    # Exceeds max_per_domain=2 for redis.io
    assert guard.is_allowed(doc3) is False
    assert guard.record_url(doc3) is False

    # Different domain should be allowed
    assert guard.is_allowed(doc_other) is True
    assert guard.record_url(doc_other) is True

    assert guard.get_domain_count("redis.io") == 2
    assert guard.get_domain_count("memcached.org") == 1


def test_domain_diversity_guard_filter_urls():
    guard = DomainDiversityGuard(max_per_domain=1)

    urls = [
        "https://example.com/page1",
        "https://example.com/page2",
        "https://other.org/page1",
    ]

    filtered = guard.filter_urls(urls)
    assert filtered == [
        "https://example.com/page1",
        "https://other.org/page1",
    ]
