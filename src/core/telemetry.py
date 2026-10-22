"""Telemetry and budget tracking utilities."""

import time

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    """Token consumption data for an agent step or execution run."""

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)

    def add(self, prompt: int, completion: int, cost: float = 0.0) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += prompt + completion
        self.estimated_cost_usd += cost


class StepTelemetry(BaseModel):
    """Telemetry captured for an individual agent execution step."""

    step_name: str
    agent_name: str
    latency_ms: float
    token_usage: TokenUsage
    status: str = "success"
    error: str | None = None


class ExecutionTimer:
    """Context manager to measure latency of async or sync blocks."""

    def __init__(self):
        self.start_time: float = 0.0
        self.end_time: float = 0.0

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.perf_counter()

    @property
    def elapsed_ms(self) -> float:
        end = self.end_time if self.end_time > 0 else time.perf_counter()
        return round((end - self.start_time) * 1000, 2)


# Model pricing registry: Rates per 1,000,000 (1M) tokens in USD (prompt_rate, completion_rate)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Google Gemini
    "gemini-3.5-flash": (0.075, 0.30),
    "gemini-3.5-flash-lite": (0.0375, 0.15),
    "gemini-2.5-flash": (0.075, 0.30),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (3.50, 10.50),
    # OpenAI
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "o1-mini": (3.00, 12.00),
    "o3-mini": (1.10, 4.40),
    # Anthropic
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "claude-3-5-haiku": (0.80, 4.00),
    # Groq / Open-source hosted
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "qwen/qwen3.8-27b": (0.20, 0.30),
    "deepseek-r1-distill-llama-70b": (0.59, 0.79),
    # Mock / Local
    "mock": (0.0, 0.0),
    "ollama": (0.0, 0.0),
}


def calculate_token_cost(
    model_name: str | None,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Calculate exact USD cost for token usage according to the active model pricing."""
    if not model_name or prompt_tokens <= 0 and completion_tokens <= 0:
        return 0.0

    # Normalize model key: remove provider prefixes if present (e.g. 'gemini:' or 'openai:')
    norm_name = model_name.lower().strip()
    if ":" in norm_name:
        norm_name = norm_name.split(":", 1)[1]
    if "/" in norm_name and not norm_name.startswith("qwen/"):
        norm_name = norm_name.split("/", 1)[1]

    # Look up pricing by direct key match or closest prefix
    pricing = MODEL_PRICING.get(norm_name)
    if pricing is None:
        for k, v in MODEL_PRICING.items():
            if k in norm_name or norm_name in k:
                pricing = v
                break

    if pricing is None:
        # Default conservative fallback (~gpt-4o-mini rates)
        prompt_rate, completion_rate = (0.15, 0.60)
    else:
        prompt_rate, completion_rate = pricing

    cost = ((prompt_tokens / 1_000_000.0) * prompt_rate) + (
        (completion_tokens / 1_000_000.0) * completion_rate
    )
    return round(cost, 6)


class StageCostAttribution(BaseModel):
    """Cost and token attribution for a specific agent stage or worker."""

    stage_name: str
    agent_role: str
    model_name: str = "default"
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    step_count: int = 1


class RunCostSummary(BaseModel):
    """Aggregate token economics and stage-by-stage cost attribution for a research run."""

    total_cost_usd: float = Field(default=0.0, ge=0.0)
    total_tokens: int = Field(default=0, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_latency_ms: float = Field(default=0.0, ge=0.0)
    by_stage: dict[str, StageCostAttribution] = Field(default_factory=dict)

    def add_stage(self, stage: StageCostAttribution) -> None:
        self.by_stage[stage.stage_name] = stage
        self.total_cost_usd = round(self.total_cost_usd + stage.cost_usd, 6)
        self.total_tokens += stage.total_tokens
        self.prompt_tokens += stage.prompt_tokens
        self.completion_tokens += stage.completion_tokens
        self.total_latency_ms = round(self.total_latency_ms + stage.latency_ms, 2)
