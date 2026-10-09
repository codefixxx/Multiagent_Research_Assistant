"""Unit and edge-case tests for the Pre-Flight Citation Validator."""

import pytest

from src.schemas.finding import FindingRecord
from src.schemas.report import Citation, ReportSection, ResearchReport
from src.validators.citation_validator import CitationValidator, validate_report_citations


@pytest.fixture
def sample_findings() -> list[FindingRecord]:
    return [
        FindingRecord(
            id="find_1",
            sub_question_id="sq_1",
            claim="Redis cluster offers sub-millisecond read/write latency.",
            source_url="https://redis.io/docs/latency",
            snippet="Redis operations typically complete within microseconds.",
        ),
        FindingRecord(
            id="find_2",
            sub_question_id="sq_2",
            claim="PostgreSQL JSONB provides indexing with GIN indexes.",
            source_url="https://postgresql.org/docs/jsonb",
            snippet="GIN indexes on JSONB columns provide efficient key queries.",
        ),
    ]


def test_validator_happy_path_all_valid(sample_findings):
    """Report with valid citations matching real findings passes cleanly."""
    report = ResearchReport(
        title="Database Performance Comparison",
        executive_summary="Summary discussing Redis [cite_1] and PostgreSQL [cite_2].",
        sections=[
            ReportSection(
                title="Performance",
                content="Redis latency is sub-millisecond [cite_1]. PostgreSQL JSONB uses GIN indexes [cite_2].",
                citation_ids=["cite_1", "cite_2"],
            )
        ],
        citations=[
            Citation(
                citation_id="cite_1",
                source_url="https://redis.io/docs/latency",
                verified_claim="Redis cluster offers sub-millisecond read/write latency.",
            ),
            Citation(
                citation_id="cite_2",
                source_url="https://postgresql.org/docs/jsonb",
                verified_claim="PostgreSQL JSONB provides indexing with GIN indexes.",
            ),
        ],
    )
    report.compile_markdown()

    result = validate_report_citations(report=report, findings=sample_findings)

    assert result.is_valid is True
    assert len(result.verified_citations) == 2
    assert len(result.hallucinated_citations) == 0
    assert len(result.orphaned_citations) == 0
    assert len(result.sanitized_report.citations) == 2


def test_validator_detects_hallucinated_url(sample_findings):
    """Citations pointing to URLs absent from the findings must be flagged as hallucinated."""
    report = ResearchReport(
        title="Database Analysis",
        executive_summary="Analysis of databases.",
        sections=[
            ReportSection(
                title="Redis vs Memcached",
                content="Memcached is multi-threaded [cite_fake].",
                citation_ids=["cite_fake"],
            )
        ],
        citations=[
            Citation(
                citation_id="cite_fake",
                source_url="https://fake-hallucinated-source.com/benchmarks",
                verified_claim="Memcached is multi-threaded.",
            )
        ],
    )
    report.compile_markdown()

    validator = CitationValidator()
    result = validator.validate(report=report, findings=sample_findings, auto_sanitize=True)

    assert result.is_valid is False
    assert "cite_fake" in result.hallucinated_citations
    # Sanitized report must prune the hallucinated citation
    assert len(result.sanitized_report.citations) == 0
    assert "cite_fake" not in result.sanitized_report.sections[0].citation_ids
    assert "[UNVERIFIED_CITATION: cite_fake]" in result.sanitized_report.sections[0].content


def test_validator_detects_undeclared_marker_in_text(sample_findings):
    """Citation markers present in text but missing from report.citations are flagged."""
    report = ResearchReport(
        title="Storage Report",
        executive_summary="Executive overview.",
        sections=[
            ReportSection(
                title="Findings",
                content="Redis is fast [cite_1], but unverified claim exists here [cite_999].",
                citation_ids=["cite_1"],
            )
        ],
        citations=[
            Citation(
                citation_id="cite_1",
                source_url="https://redis.io/docs/latency",
                verified_claim="Redis cluster offers sub-millisecond read/write latency.",
            )
        ],
    )
    report.compile_markdown()

    result = validate_report_citations(report=report, findings=sample_findings, auto_sanitize=True)

    assert result.is_valid is False
    assert "cite_999" in result.hallucinated_citations
    assert "cite_1" in result.verified_citations


def test_validator_detects_orphaned_citation(sample_findings):
    """Citations declared in the citations list but never referenced in the body are identified."""
    report = ResearchReport(
        title="Storage Report",
        executive_summary="Overview mentioning only Redis [cite_1].",
        sections=[
            ReportSection(
                title="Redis Notes",
                content="Redis latency is minimal [cite_1].",
                citation_ids=["cite_1"],
            )
        ],
        citations=[
            Citation(
                citation_id="cite_1",
                source_url="https://redis.io/docs/latency",
                verified_claim="Redis cluster offers sub-millisecond latency.",
            ),
            Citation(
                citation_id="cite_2",
                source_url="https://postgresql.org/docs/jsonb",
                verified_claim="Postgres JSONB documentation.",
            ),
        ],
    )
    report.compile_markdown()

    result = validate_report_citations(report=report, findings=sample_findings)

    # Valid because no hallucinated URLs, but cite_2 is orphaned
    assert result.is_valid is True
    assert "cite_2" in result.orphaned_citations
    assert "cite_1" not in result.orphaned_citations
