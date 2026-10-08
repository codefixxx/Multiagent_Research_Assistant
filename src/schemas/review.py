"""Pydantic schemas for the Reviewer Specialist and Supervisor review decisions."""

from pydantic import BaseModel, Field


class ReviewEvaluation(BaseModel):
    """Structured evaluation output produced by the Reviewer specialist."""

    is_approved: bool = Field(
        description="Whether the research findings adequately address the current sub-question."
    )
    quality_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score from 0.0 to 1.0 regarding factual completeness and citation quality.",
    )
    feedback: str = Field(
        description="Concise rationale for approval or specific gaps that require a single revision pass."
    )
    missing_aspects: list[str] = Field(
        default_factory=list,
        description="Specific factual details, numbers, or sources missing from current findings.",
    )
