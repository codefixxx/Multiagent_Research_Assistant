"""Pydantic request and response schemas for the FastAPI service."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, SecretStr

from src.core.telemetry import RunCostSummary, TokenUsage
from src.schemas.plan import ResearchPlan
from src.schemas.report import ResearchReport
from src.schemas.trace import StepTrace
from src.validators.citation_validator import CitationValidationResult
from src.validators.rag_scorer import RAGQualityScore


class ModelMatrixConfig(BaseModel):
    """Configures specialized model choices for each agent role."""

    planner: str | None = Field(default=None, description="Model for the Planner agent")
    researcher: str | None = Field(
        default=None, description="Model for parallel Researcher workers"
    )
    reviewer: str | None = Field(default=None, description="Model for the Reviewer agent")
    writer: str | None = Field(default=None, description="Model for the Report Writer agent")


class APIKeysConfig(BaseModel):
    """Optional ephemeral user API keys for BYOK (Bring Your Own Key) execution.

    Keys are strongly typed as SecretStr to prevent leakage in logs, traces,
    JSON serializations, or exception representations.
    """

    gemini: SecretStr | None = Field(default=None, description="Google Gemini API Key")
    openai: SecretStr | None = Field(default=None, description="OpenAI API Key")
    anthropic: SecretStr | None = Field(default=None, description="Anthropic API Key")
    groq: SecretStr | None = Field(default=None, description="Groq API Key")
    tavily: SecretStr | None = Field(default=None, description="Tavily Search API Key")

    def get_secret(self, provider: str) -> str | None:
        """Safely expose the raw plaintext secret strictly for LLM client construction."""
        val = getattr(self, provider.lower(), None)
        if val is None:
            return None
        if isinstance(val, SecretStr):
            return val.get_secret_value()
        return str(val)

    def to_exposed_dict(self) -> dict[str, str | None]:
        """Convert to raw dictionary with exposed secret values for internal factory consumption only."""
        return {
            "gemini": self.get_secret("gemini"),
            "openai": self.get_secret("openai"),
            "anthropic": self.get_secret("anthropic"),
            "groq": self.get_secret("groq"),
            "tavily": self.get_secret("tavily"),
        }

    def has_keys(self) -> bool:
        """Check if any provider secret key is configured."""
        return any(v is not None for v in self.to_exposed_dict().values())


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
    focus_mode: str = Field(
        default="general",
        description="Domain focus mode: 'general', 'academic' (scholarly literature/arXiv), 'technical' (architecture/code/benchmarks), or 'financial' (SEC filings/earnings/market).",
    )
    hitl_enabled: bool = Field(
        default=False,
        description="When True, pauses execution after research planning to allow human review, editing, or regeneration before parallel research fans out.",
    )
    model_matrix: ModelMatrixConfig | None = Field(
        default=None,
        description="Optional custom model assignments per agent role.",
    )
    api_keys: APIKeysConfig | None = Field(
        default=None,
        description="Optional ephemeral user API keys for BYOK execution.",
    )


class PlanSteerAction(str):
    APPROVE = "approve"
    MODIFY = "modify"
    REGENERATE = "regenerate"
    REJECT = "reject"


class PlanSteerRequest(BaseModel):
    """User steering instruction to approve, edit, or regenerate a research plan."""

    action: str = Field(
        description="Steering action: 'approve' (continue as-is), 'modify' (continue with modified_plan), 'regenerate' (re-plan with feedback), or 'reject' (cancel).",
    )
    modified_plan: ResearchPlan | None = Field(
        default=None,
        description="Curated ResearchPlan containing user-modified or newly added sub-questions if action is 'modify'.",
    )
    feedback: str | None = Field(
        default=None,
        description="Human steering feedback or prompt guidance for re-planning if action is 'regenerate'.",
    )


class PlanSteerResponse(BaseModel):
    """Result of submitting a plan steering action."""

    run_id: str
    action: str
    status: str
    message: str


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
    plan: ResearchPlan | None = Field(
        default=None,
        description="Decomposed research plan (available during review and completion).",
    )
    report: ResearchReport | None = None
    citation_validation: CitationValidationResult | None = None
    cost_summary: RunCostSummary | None = None
    rag_score: RAGQualityScore | None = None
    focus_mode: str | None = Field(
        default="general", description="Focus mode configured for the run."
    )
    hitl_enabled: bool = Field(
        default=False, description="Whether Human-in-the-Loop review is active for this run."
    )
    error_message: str | None = None
    error_code: str | None = None
    error_suggestion: str | None = None
    error_details: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ResearchHistoryItem(BaseModel):
    """Summary of a past research job retained in Redis."""

    run_id: str
    query: str
    status: str
    focus_mode: str | None = Field(
        default="general", description="Focus mode configured for the run."
    )
    created_at: str | None = None
    updated_at: str | None = None
    step_count: int = 0
    total_tokens: int = 0
    findings_count: int = 0
    cost_summary: RunCostSummary | None = None
    rag_score: RAGQualityScore | None = None
    has_report: bool = False
    error_message: str | None = None
    error_code: str | None = None
    error_suggestion: str | None = None


class ResearchHistoryResponse(BaseModel):
    """Paginated list of recent research runs within the retention window."""

    total: int = Field(description="Total number of active runs retained in the index.")
    runs: list[ResearchHistoryItem] = Field(default_factory=list)
    limit: int = Field(default=20)
    offset: int = Field(default=0)


class AuditTraceResponse(BaseModel):
    """Full execution trace detailing step-by-step agent interactions."""

    run_id: str
    query: str
    status: str
    total_latency_ms: float = 0.0
    total_tokens: TokenUsage = Field(default_factory=TokenUsage)
    step_count: int = 0
    steps: list[StepTrace] = Field(default_factory=list)
    cost_summary: RunCostSummary | None = None
    rag_score: RAGQualityScore | None = None
    spans: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    error_code: str | None = None
    error_suggestion: str | None = None


class StreamEventData(BaseModel):
    """Payload for real-time Server-Sent Events (SSE)."""

    event: str
    run_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    payload: dict[str, Any] = Field(default_factory=dict)


class ModelValidationRequest(BaseModel):
    """Payload to test and verify LLM credentials and model availability."""

    provider: str | None = Field(
        default=None, description="LLM provider: gemini, groq, openai, anthropic, ollama"
    )
    model_name: str | None = Field(
        default=None, description="Model identifier to test (e.g. 'gemini-2.5-flash')"
    )
    api_key: str | None = Field(default=None, description="Optional API key to test")


class ModelValidationResponse(BaseModel):
    """Validation response indicating whether model and credentials are functional."""

    valid: bool
    provider: str
    model: str
    message: str
    code: str | None = None
    suggestion: str | None = None
    sample_response: str | None = None
