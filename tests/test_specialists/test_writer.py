"""Isolated unit tests for Writer Specialist."""

import pytest

from src.agents.writer import format_findings_for_writer, write_report
from src.schemas.finding import FindingRecord
from src.schemas.report import ResearchReport


@pytest.mark.asyncio
async def test_writer_in_isolation(mock_llm):
    """Writer must synthesize findings into structured report with citations."""
    query = "Evaluate state of fault-tolerant quantum computing in 2024"
    findings = [
        FindingRecord(
            id="find_1",
            sub_question_id="sq_1",
            claim="Demonstrated 48 logical qubits using neutral atoms.",
            source_url="https://nature.com/articles/quantum-qubits-2024",
            snippet="We demonstrate 48 logical qubits...",
        ),
        FindingRecord(
            id="find_2",
            sub_question_id="sq_1",
            claim="Two-qubit gate fidelities reached 99.9%.",
            source_url="https://arxiv.org/abs/2401.00123",
            snippet="Achieving 99.9% fidelity in two-qubit entangling gates.",
        ),
    ]

    report, tokens, latency = await write_report(
        query=query,
        findings=findings,
        llm=mock_llm,
    )

    assert isinstance(report, ResearchReport)
    assert len(report.title) > 0
    assert len(report.executive_summary) > 0
    assert len(report.sections) >= 1
    assert len(report.citations) >= 1
    assert len(report.markdown_output) > 0

    # Citations in report must have valid URLs
    for cite in report.citations:
        assert cite.citation_id.startswith("[cite_") or cite.citation_id.startswith("cite_")
        assert cite.source_url.startswith("http")

    assert tokens.total_tokens > 0
    assert latency >= 0.0


def test_format_findings_for_writer():
    findings = [
        FindingRecord(
            id="f1",
            sub_question_id="sq_1",
            claim="Claim 1",
            source_url="https://test.com",
            snippet="Snippet 1",
        )
    ]
    formatted = format_findings_for_writer(findings)
    assert "[cite_1]" in formatted
    assert "https://test.com" in formatted
    assert "Claim 1" in formatted
