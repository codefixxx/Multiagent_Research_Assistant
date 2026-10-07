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
