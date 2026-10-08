"""Unit tests for deterministic hard budget enforcer."""

import time

from src.core.telemetry import TokenUsage
from src.graph.budgets import BudgetLimits, evaluate_budget
from src.graph.state import ResearchState


def test_budget_within_limits():
    tokens = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
    state = ResearchState(
        total_tokens=tokens,
        start_time=time.time(),
        current_sub_question_index=1,
    )
    result = evaluate_budget(state)
    assert result.is_exceeded is False
    assert result.reason is None


def test_token_ceiling_breach():
    tokens = TokenUsage(prompt_tokens=100000, completion_tokens=60000, total_tokens=160000)
    state = ResearchState(
        total_tokens=tokens,
        start_time=time.time(),
        current_sub_question_index=1,
    )
    limits = BudgetLimits(max_budget_tokens=150000)
    result = evaluate_budget(state, limits=limits)
    assert result.is_exceeded is True
    assert result.exceeded_metric == "tokens"
    assert result.reason is not None
    assert "Token budget ceiling exceeded" in result.reason


def test_wall_clock_ceiling_breach():
    tokens = TokenUsage(total_tokens=500)
    # Start time set 300 seconds in the past
    state = ResearchState(
        total_tokens=tokens,
        start_time=time.time() - 300,
        current_sub_question_index=1,
    )
    limits = BudgetLimits(max_wall_clock_seconds=240.0)
    result = evaluate_budget(state, limits=limits)
    assert result.is_exceeded is True
    assert result.exceeded_metric == "wall_clock"
    assert result.reason is not None
    assert "Wall-clock ceiling exceeded" in result.reason


def test_sub_question_cap_breach():
    tokens = TokenUsage(total_tokens=500)
    state = ResearchState(
        total_tokens=tokens,
        start_time=time.time(),
        current_sub_question_index=4,
    )
    limits = BudgetLimits(max_sub_questions=4)
    result = evaluate_budget(state, limits=limits)
    assert result.is_exceeded is True
    assert result.exceeded_metric == "sub_questions"
    assert result.reason is not None
    assert "Sub-question cap reached" in result.reason
