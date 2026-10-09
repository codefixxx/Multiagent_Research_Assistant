"""Unit tests for Supervisor routing and single-pass revision gate."""

import time

from langgraph.types import Send

from src.core.telemetry import TokenUsage
from src.graph.state import ResearchState
from src.graph.supervisor import (
    route_after_consolidator,
    route_after_planner,
    route_after_reviewer,
)
from src.schemas.finding import FindingRecord
from src.schemas.plan import ResearchPlan, SubQuestion


def test_route_after_planner():
    # Valid plan fans out to researcher workers via LangGraph Send API
    plan = ResearchPlan(
        query="Test query",
        objective="Test objective",
        sub_questions=[
            SubQuestion(id="sq_1", question="Q1", rationale="R1"),
            SubQuestion(id="sq_2", question="Q2", rationale="R2"),
        ],
    )
    state = ResearchState(plan=plan, run_id="run_123", query="Test query")
    decision = route_after_planner(state)

    assert isinstance(decision, list)
    assert len(decision) == 2
    assert all(isinstance(s, Send) for s in decision)
    assert decision[0].node == "researcher"
    assert decision[0].arg["sub_question"].id == "sq_1"
    assert decision[1].node == "researcher"
    assert decision[1].arg["sub_question"].id == "sq_2"

    # Empty plan routes to failed
    assert route_after_planner(ResearchState(plan=None)) == "failed"


def test_route_after_consolidator():
    # Normal state with findings routes to writer
    plan = ResearchPlan(
        query="Test query",
        objective="Test objective",
        sub_questions=[SubQuestion(id="sq_1", question="Q1", rationale="R1")],
    )
    normal_state = ResearchState(
        plan=plan,
        findings=[
            FindingRecord(
                id="f_1",
                sub_question_id="sq_1",
                claim="Claim 1",
                source_url="https://example.com",
                snippet="Snippet 1",
            )
        ],
        total_tokens=TokenUsage(total_tokens=500),
    )
    assert route_after_consolidator(normal_state) == "writer"

    # Pre-breached token budget routes to emergency_writer
    breached_state = ResearchState(
        plan=plan,
        findings=[],
        total_tokens=TokenUsage(total_tokens=200000),
    )
    assert route_after_consolidator(breached_state) == "emergency_writer"


def test_supervisor_single_pass_revision_gate():
    """Supervisor must allow at most ONE revision pass per sub-question."""
    plan = ResearchPlan(
        query="Test query",
        objective="Test objective",
        sub_questions=[
            SubQuestion(id="sq_1", question="Q1", rationale="R1"),
            SubQuestion(id="sq_2", question="Q2", rationale="R2"),
        ],
    )

    # First pass: reviewer gave negative feedback, revision_count = 0
    # Must route back to researcher for single permitted revision
    state_pass_1 = ResearchState(
        plan=plan,
        current_sub_question_index=0,
        revision_count=0,
        review_feedback="Need concrete latency numbers",
        start_time=time.time(),
        total_tokens=TokenUsage(total_tokens=1000),
    )
    decision_1 = route_after_reviewer(state_pass_1)
    assert decision_1 == "researcher"

    # Second pass: reviewer gave negative feedback AGAIN, but revision_count = 1
    # MUST NOT loop again. Must force advance to next sub-question!
    state_pass_2 = ResearchState(
        plan=plan,
        current_sub_question_index=0,
        revision_count=1,
        review_feedback="Still need more data",
        start_time=time.time(),
        total_tokens=TokenUsage(total_tokens=2000),
    )
    decision_2 = route_after_reviewer(state_pass_2)
    assert decision_2 == "researcher"  # Advanced to sq_2!


def test_supervisor_routes_to_writer_when_subquestions_completed():
    plan = ResearchPlan(
        query="Test query",
        objective="Test objective",
        sub_questions=[SubQuestion(id="sq_1", question="Q1", rationale="R1")],
    )
    # Index is 0, so next_idx is 1 == len(sub_questions) -> route to writer
    state = ResearchState(
        plan=plan,
        current_sub_question_index=0,
        revision_count=1,
        review_feedback=None,
        start_time=time.time(),
        total_tokens=TokenUsage(total_tokens=1000),
    )
    decision = route_after_reviewer(state)
    assert decision == "writer"


def test_supervisor_routes_to_emergency_writer_on_token_budget_breach():
    plan = ResearchPlan(
        query="Test query",
        objective="Test objective",
        sub_questions=[SubQuestion(id="sq_1", question="Q1", rationale="R1")],
    )
    state = ResearchState(
        plan=plan,
        current_sub_question_index=0,
        revision_count=0,
        start_time=time.time(),
        total_tokens=TokenUsage(total_tokens=200000),  # Exceeds 150k
    )
    decision = route_after_reviewer(state)
    assert decision == "emergency_writer"
