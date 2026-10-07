"""Isolated unit tests for Planner Specialist."""

import pytest

from src.agents.planner import plan_research
from src.schemas.plan import ResearchPlan, SubQuestionStatus


@pytest.mark.asyncio
async def test_planner_in_isolation(mock_llm):
    """Planner must return structured subquestions with valid Pydantic fields."""
    query = "Evaluate state of fault-tolerant quantum computing in 2024"
    plan, tokens, latency = await plan_research(query=query, llm=mock_llm)

    assert isinstance(plan, ResearchPlan)
    assert len(plan.sub_questions) >= 1
    assert len(plan.sub_questions) <= 4

    for sq in plan.sub_questions:
        assert sq.id.startswith("sq_")
        assert len(sq.question) > 5
        assert sq.status == SubQuestionStatus.PENDING
        assert isinstance(sq.search_queries, list)

    assert tokens.total_tokens > 0
    assert latency >= 0.0


@pytest.mark.asyncio
async def test_planner_subquestions_are_specific(mock_llm):
    """Sub-questions must contain targeted technical queries rather than blank strings."""
    query = "Compare Redis vs Memcached latency benchmarks"
    plan, _, _ = await plan_research(query=query, llm=mock_llm)

    for sq in plan.sub_questions:
        assert sq.rationale != ""
        assert len(sq.search_queries) > 0
