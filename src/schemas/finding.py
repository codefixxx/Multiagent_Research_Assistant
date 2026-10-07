"""Pydantic schemas for the Researcher Specialist and web evidence provenance."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ExtractionStatus(StrEnum):
    SUCCESS = "success"
    NO_RESULTS = "no_results"
    RATE_LIMITED = "rate_limited"
    PAYWALLED = "paywalled"
    TIMED_OUT = "timed_out"
    BLOCKED = "blocked"
    ERROR = "error"


class FindingRecord(BaseModel):
    """An atomic factual claim backed by exact source URL, snippet, and timestamp provenance."""

    id: str = Field(description="Unique ID for this finding record, e.g., 'find_1', 'find_2'")
    sub_question_id: str = Field(description="The ID of the sub-question this finding answers.")
    claim: str = Field(
        description="The specific, verified factual statement or statistic extracted from the source."
    )
    source_url: str = Field(
        description="The exact HTTP/HTTPS URL from which this snippet and claim were obtained."
    )
    snippet: str = Field(
        description="Direct quote or contextual excerpt from the source webpage demonstrating the claim."
    )
    retrieval_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp when the evidence was retrieved.",
    )


class ResearcherOutput(BaseModel):
    """Structured hand-off output produced by the Researcher specialist."""

    sub_question_id: str = Field(description="ID of the sub-question that was investigated.")
    is_answered: bool = Field(
        description="Whether sufficient factual evidence was gathered to consider the sub-question answered."
    )
    findings: list[FindingRecord] = Field(
        default_factory=list,
        description="Structured findings with complete provenance.",
    )
    summary: str = Field(
        description="A concise factual synthesis of what was learned during this research pass."
    )
    status: ExtractionStatus = Field(
        default=ExtractionStatus.SUCCESS,
        description="Outcome status of the research and retrieval step.",
    )
