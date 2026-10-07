"""Isolated unit tests for Researcher Specialist."""

import pytest

from src.agents.researcher import research_subquestion
from src.schemas.finding import ExtractionStatus, ResearcherOutput
from src.schemas.plan import SubQuestion, SubQuestionStatus


@pytest.mark.asyncio
async def test_researcher_in_isolation(mock_llm):
    """Researcher must extract findings with strict provenance and answer status."""
    sub_q = SubQuestion(
        id="sq_1",
        question="What logical qubit fidelity milestones were reached?",
        rationale="Measures fault-tolerance.",
        search_queries=["logical qubit fidelity benchmarks"],
        status=SubQuestionStatus.IN_PROGRESS,
    )
    evidence = (
        "Document: https://nature.com/articles/quantum-qubits-2024\n"
        "We demonstrate fault-tolerant operation on 48 logical qubits..."
    )

    output, tokens, latency = await research_subquestion(
        sub_question=sub_q,
        evidence_context=evidence,
        llm=mock_llm,
    )

    assert isinstance(output, ResearcherOutput)
    assert output.sub_question_id == "sq_1"
    assert output.status == ExtractionStatus.SUCCESS
    assert output.is_answered is True
    assert len(output.findings) >= 1

    # Verify provenance on every finding
    for finding in output.findings:
        assert finding.sub_question_id == "sq_1"
        assert finding.source_url.startswith("http")
        assert len(finding.claim) > 0
        assert len(finding.snippet) > 0
        assert finding.retrieval_timestamp is not None

    assert tokens.total_tokens > 0
    assert latency >= 0.0
