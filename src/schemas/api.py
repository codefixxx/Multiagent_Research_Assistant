"""Pydantic request and response schemas for the FastAPI service."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from src.core.telemetry import TokenUsage
from src.schemas.report import ResearchReport
from src.schemas.trace import StepTrace
from src.validators.citation_validator import CitationValidationResult


class ResearchRequest(BaseModel):
    """Payload for submitting a new background research job."""

    query: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        description="The core research query or topic to investigate.",
        examples=["Compare Redis vs PostgreSQL for multi-agent state persistence"],
    )
    max_sub_questions: int | None = Field(
        default=None,
        ge=1,
        le=8,
        description="Optional upper bound on generated research sub-questions.",
    )
    max_tokens: int | None = Field(
        default=None,
        ge=1000,
        description="Optional hard token budget limit for the run.",
    )
    max_wall_clock_seconds: float | None = Field(
        default=None,
        ge=10.0,
        le=600.0,
        description="Optional execution time limit before emergency synthesis triggers.",
    )
    deep_scrape: bool = Field(
        default=True,
        description="Whether to perform deep HTML page scraping and provenance extraction.",
    )


class ResearchSubmissionResponse(BaseModel):
    """Immediate acknowledgment returned upon job submission (HTTP 202)."""

    run_id: str = Field(description="Unique identifier for tracking the research job.")
    status: str = Field(default="queued", description="Initial lifecycle state of the run.")
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 creation timestamp.",
    )
    message: str = Field(
        default="Research job accepted and queued for execution.",
        description="Human-readable dispatch confirmation.",
    )


class ResearchStatusResponse(BaseModel):
    """Current progress and results status for a research run."""

    run_id: str
    query: str
    status: str
    progress_pct: int = Field(
        ge=0,
        le=100,
        description="Estimated completion percentage based on agent state transitions.",
    )
    current_node: str | None = None
    step_count: int = 0
    total_tokens: int = 0
    findings_count: int = 0
    report: ResearchReport | None = None
    citation_validation: CitationValidationResult | None = None
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class AuditTraceResponse(BaseModel):
    """Full execution trace detailing step-by-step agent interactions."""

    run_id: str
    query: str
    status: str
    total_latency_ms: float = 0.0
    total_tokens: TokenUsage = Field(default_factory=TokenUsage)
    step_count: int = 0
    steps: list[StepTrace] = Field(default_factory=list)
    error: str | None = None


class StreamEventData(BaseModel):
    """Payload for real-time Server-Sent Events (SSE)."""

    event: str
    run_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    payload: dict[str, Any] = Field(default_factory=dict)
