"""Unit tests for token cost calculation and stage cost attribution."""

from src.core.telemetry import (
    RunCostSummary,
    StageCostAttribution,
    calculate_token_cost,
)


def test_calculate_token_cost_zero_or_empty():
    assert calculate_token_cost(None, 100, 100) == 0.0
    assert calculate_token_cost("gemini-2.5-flash", 0, 0) == 0.0
    assert calculate_token_cost("mock", 1000, 500) == 0.0


def test_calculate_token_cost_known_models():
    # gemini-2.5-flash: prompt 0.075 / 1M, completion 0.30 / 1M
    cost_gemini = calculate_token_cost("gemini-2.5-flash", 1_000_000, 1_000_000)
    assert round(cost_gemini, 4) == round(0.075 + 0.30, 4)

    # gpt-4o-mini: prompt 0.15 / 1M, completion 0.60 / 1M
    cost_openai = calculate_token_cost("gpt-4o-mini", 1_000_000, 1_000_000)
    assert round(cost_openai, 4) == round(0.15 + 0.60, 4)

    # claude-3-5-sonnet: prompt 3.00 / 1M, completion 15.00 / 1M
    cost_anthropic = calculate_token_cost("claude-3-5-sonnet", 1_000_000, 1_000_000)
    assert round(cost_anthropic, 4) == round(3.00 + 15.00, 4)


def test_calculate_token_cost_prefix_stripping():
    # google:gemini-2.5-flash should resolve to gemini-2.5-flash
    cost_prefixed = calculate_token_cost("google:gemini-2.5-flash", 100_000, 100_000)
    cost_direct = calculate_token_cost("gemini-2.5-flash", 100_000, 100_000)
    assert cost_prefixed == cost_direct


def test_calculate_token_cost_unknown_model_fallback():
    # Unknown model falls back to default conservative rates (0.15, 0.60)
    cost_unknown = calculate_token_cost("super-new-unknown-llm", 1_000_000, 1_000_000)
    assert round(cost_unknown, 4) == round(0.15 + 0.60, 4)


def test_run_cost_summary_aggregation():
    summary = RunCostSummary()
    assert summary.total_cost_usd == 0.0
    assert summary.total_tokens == 0

    stage1 = StageCostAttribution(
        stage_name="planner_1",
        agent_role="planner",
        model_name="gemini-2.5-flash",
        prompt_tokens=500,
        completion_tokens=200,
        total_tokens=700,
        cost_usd=0.0001,
        latency_ms=120.5,
    )
    stage2 = StageCostAttribution(
        stage_name="researcher_1",
        agent_role="researcher",
        model_name="gemini-2.5-flash",
        prompt_tokens=1500,
        completion_tokens=800,
        total_tokens=2300,
        cost_usd=0.00035,
        latency_ms=450.0,
    )

    summary.add_stage(stage1)
    summary.add_stage(stage2)

    assert summary.total_tokens == 3000
    assert summary.prompt_tokens == 2000
    assert summary.completion_tokens == 1000
    assert summary.total_cost_usd == 0.00045
    assert summary.total_latency_ms == 570.5
    assert "planner_1" in summary.by_stage
    assert "researcher_1" in summary.by_stage
