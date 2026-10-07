"""Pydantic schemas for the Planner Specialist."""

from enum import StrEnum

from pydantic import BaseModel, Field


class SubQuestionStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class SubQuestion(BaseModel):
    """An atomic, answerable sub-question derived from the main research query."""

    id: str = Field(description="Unique identifier for the sub-question, e.g., 'sq_1', 'sq_2'")
    question: str = Field(
        description="Clear, specific, and answerable sub-question without vague phrasing."
    )
    rationale: str = Field(
        description="Why answering this sub-question is necessary to address the root research query."
    )
    search_queries: list[str] = Field(
        default_factory=list,
        description="1 to 3 targeted web search query strings designed to find factual evidence for this sub-question.",
    )
    status: SubQuestionStatus = Field(default=SubQuestionStatus.PENDING)


class ResearchPlan(BaseModel):
    """Structured plan containing decomposed sub-questions and overall research objective."""

    query: str = Field(description="The original user research question.")
    objective: str = Field(
        description="Concise description of what a successful, comprehensive research report must deliver."
    )
    sub_questions: list[SubQuestion] = Field(
        min_length=1,
        max_length=4,
        description="A list of 2 to 4 distinct, non-overlapping sub-questions.",
    )
