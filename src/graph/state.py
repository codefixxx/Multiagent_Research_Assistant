"""Graph state definition for the LangGraph multi-agent research supervisor."""

import operator
from typing import Annotated, Any, Literal

from typing_extensions import TypedDict

from src.core.telemetry import TokenUsage
from src.schemas.finding import FindingRecord
from src.schemas.plan import ResearchPlan
from src.schemas.report import ResearchReport
from src.schemas.trace import StepTrace

RunStatus = Literal[
    "planning",
    "researching",
    "reviewing",
    "writing",
    "completed",
    "failed",
    "budget_exceeded",
]


def reduce_token_usage(left: Any, right: Any) -> TokenUsage:
    """Accumulate TokenUsage across sequential and parallel graph nodes."""
    def _to_usage(val: Any) -> TokenUsage:
        if isinstance(val, TokenUsage):
            return val
        if isinstance(val, dict):
            return TokenUsage(**val)
        return TokenUsage()

    l_u = _to_usage(left)
    r_u = _to_usage(right)
    return TokenUsage(
        prompt_tokens=l_u.prompt_tokens + r_u.prompt_tokens,
        completion_tokens=l_u.completion_tokens + r_u.completion_tokens,
        total_tokens=l_u.total_tokens + r_u.total_tokens,
        estimated_cost_usd=round(l_u.estimated_cost_usd + r_u.estimated_cost_usd, 6),
    )


class ResearchState(TypedDict, total=False):
    """The single source of truth state object shared across all LangGraph nodes."""

    # Identity and input query
    run_id: str
    query: str

    # Planning
    plan: ResearchPlan | None

    # Iteration pointer and accumulated evidence
    current_sub_question_index: int
    findings: Annotated[list[FindingRecord], operator.add]
    current_sub_question_findings: list[FindingRecord]

    # Review loop control (STRICT CAP: max 1 revision per sub-question)
    revision_count: int
    review_feedback: str | None

    # Final report artifact
    report: ResearchReport | None

    # Lifecycle status
    status: RunStatus

    # Hard budget telemetry and audit trace
    total_tokens: Annotated[TokenUsage, reduce_token_usage]
    start_time: float
    step_count: Annotated[int, operator.add]
    audit_traces: Annotated[list[StepTrace], operator.add]

    # Error handling
    error_message: str | None
