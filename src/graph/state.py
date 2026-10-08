"""Graph state definition for the LangGraph multi-agent research supervisor."""

from typing import Literal

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


class ResearchState(TypedDict, total=False):
    """The single source of truth state object shared across all LangGraph nodes."""

    # Identity and input query
    run_id: str
    query: str

    # Planning
    plan: ResearchPlan | None

    # Iteration pointer and accumulated evidence
    current_sub_question_index: int
    findings: list[FindingRecord]
    current_sub_question_findings: list[FindingRecord]

    # Review loop control (STRICT CAP: max 1 revision per sub-question)
    revision_count: int
    review_feedback: str | None

    # Final report artifact
    report: ResearchReport | None

    # Lifecycle status
    status: RunStatus

    # Hard budget telemetry and audit trace
    total_tokens: TokenUsage
    start_time: float
    step_count: int
    audit_traces: list[StepTrace]

    # Error handling
    error_message: str | None
