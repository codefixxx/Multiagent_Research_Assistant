"""Unit tests for domain Pydantic schemas."""

import pytest
from pydantic import ValidationError

from src.schemas.finding import FindingRecord
from src.schemas.plan import ResearchPlan, SubQuestion, SubQuestionStatus
from src.schemas.report import Citation, ReportSection, ResearchReport


def test_subquestion_schema_validation():
    sq = SubQuestion(
        id="sq_1",
        question="What is the latency benchmark for vector indexing?",
        rationale="Essential for performance analysis.",
        search_queries=["vector index latency benchmark"],
    )
    assert sq.id == "sq_1"
    assert sq.status == SubQuestionStatus.PENDING
    assert len(sq.search_queries) == 1


def test_research_plan_bounds():
    # Valid plan with 2 subquestions
    plan = ResearchPlan(
        query="Test query",
        objective="Test objective",
        sub_questions=[
            SubQuestion(id="sq_1", question="Q1", rationale="R1"),
            SubQuestion(id="sq_2", question="Q2", rationale="R2"),
        ],
    )
    assert len(plan.sub_questions) == 2

    # Should fail if empty sub_questions (min_length=1)
    with pytest.raises(ValidationError):
        ResearchPlan(
            query="Test query",
            objective="Test objective",
            sub_questions=[],
        )

    # Should fail if > 4 sub_questions (max_length=4)
    with pytest.raises(ValidationError):
        ResearchPlan(
            query="Test query",
            objective="Test objective",
            sub_questions=[
                SubQuestion(id=f"sq_{i}", question=f"Q{i}", rationale=f"R{i}") for i in range(5)
            ],
        )


def test_finding_record_and_provenance():
    finding = FindingRecord(
        id="find_10",
        sub_question_id="sq_1",
        claim="Latency dropped by 45% using HNSW graph indexes.",
        source_url="https://example.com/hnsw-benchmark",
        snippet="HNSW graph traversal showed 45% latency reduction under concurrent load.",
    )
    assert finding.id == "find_10"
    assert finding.retrieval_timestamp is not None
    assert "45%" in finding.claim


def test_research_report_markdown_compilation():
    report = ResearchReport(
        title="Vector Database Benchmarks",
        executive_summary="Summary of findings.",
        sections=[
            ReportSection(
                title="Indexing", content="HNSW scales well [cite_1].", citation_ids=["[cite_1]"]
            )
        ],
        citations=[
            Citation(
                citation_id="[cite_1]",
                source_url="https://example.com",
                verified_claim="HNSW scaling",
            )
        ],
    )
    md = report.compile_markdown()
    assert "# Vector Database Benchmarks" in md
    assert "## Executive Summary" in md
    assert "## References & Citations" in md
    assert "[cite_1]" in md
