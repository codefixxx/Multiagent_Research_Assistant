"""Deterministic Hard Budget Enforcement Engine.

Enforces resource and cost ceilings programmatically inside the LangGraph state machine,
rather than relying on conversational prompts.
"""

import time

from pydantic import BaseModel, Field

from src.config import settings
from src.core.logger import logger
from src.graph.state import ResearchState


class BudgetLimits(BaseModel):
    """Configurable boundaries for a single research execution run."""

    max_sub_questions: int = Field(default_factory=lambda: settings.MAX_SUB_QUESTIONS)
    max_searches_per_sub_question: int = Field(
        default_factory=lambda: settings.MAX_SEARCHES_PER_SUB_QUESTION
    )
    max_budget_tokens: int = Field(default_factory=lambda: settings.MAX_BUDGET_TOKENS)
    max_wall_clock_seconds: float = Field(
        default_factory=lambda: float(settings.MAX_WALL_CLOCK_SECONDS)
    )
    max_revisions_per_subquestion: int = Field(
        default_factory=lambda: settings.MAX_REVISIONS_PER_SUBQUESTION
    )


class BudgetCheckResult(BaseModel):
    """Result of evaluating current state against budget limits."""

    is_exceeded: bool
    exceeded_metric: str | None = None
    reason: str | None = None


def evaluate_budget(
    state: ResearchState,
    limits: BudgetLimits | None = None,
) -> BudgetCheckResult:
    """Evaluate whether the current graph state has breached any hard operational limits.

    Checks:
        1. Cumulative token spend against max_budget_tokens ceiling.
        2. Wall-clock execution time against max_wall_clock_seconds ceiling.
        3. Completed sub-questions against max_sub_questions ceiling.

    Returns:
        BudgetCheckResult indicating if emergency synthesis is mandatory.
    """
    effective_limits = limits or BudgetLimits()

    # 1. Check cumulative token ceiling
    tokens = state.get("total_tokens")
    current_tokens = tokens.total_tokens if tokens else 0
    if current_tokens >= effective_limits.max_budget_tokens:
        reason = (
            f"Token budget ceiling exceeded: {current_tokens:,} tokens spent "
            f"(hard limit: {effective_limits.max_budget_tokens:,} tokens)."
        )
        logger.warning("Hard budget limit reached", metric="tokens", reason=reason)
        return BudgetCheckResult(
            is_exceeded=True,
            exceeded_metric="tokens",
            reason=reason,
        )

    # 2. Check wall-clock ceiling
    start_time = state.get("start_time", 0.0)
    if start_time > 0:
        elapsed = time.time() - start_time
        if elapsed >= effective_limits.max_wall_clock_seconds:
            reason = (
                f"Wall-clock ceiling exceeded: {elapsed:.1f}s elapsed "
                f"(hard limit: {effective_limits.max_wall_clock_seconds:.1f}s)."
            )
            logger.warning("Hard budget limit reached", metric="wall_clock", reason=reason)
            return BudgetCheckResult(
                is_exceeded=True,
                exceeded_metric="wall_clock",
                reason=reason,
            )

    # 3. Check sub-question count ceiling
    current_index = state.get("current_sub_question_index", 0)
    if current_index >= effective_limits.max_sub_questions:
        reason = (
            f"Sub-question cap reached: {current_index} sub-questions processed "
            f"(hard limit: {effective_limits.max_sub_questions})."
        )
        logger.info("Sub-question limit reached", metric="sub_questions", reason=reason)
        return BudgetCheckResult(
            is_exceeded=True,
            exceeded_metric="sub_questions",
            reason=reason,
        )

    return BudgetCheckResult(is_exceeded=False)
