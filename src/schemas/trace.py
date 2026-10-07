"""Pydantic schemas for step-level audit tracing and execution telemetry."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from src.core.telemetry import TokenUsage


class ToolCallRecord(BaseModel):
    """Log of a specific tool invocation executed during an agent step."""

    tool_name: str
    tool_input: dict[str, Any] = Field(default_factory=dict)
    tool_output_summary: str = ""
    latency_ms: float = 0.0
    status: str = "success"


class StepTrace(BaseModel):
    """Step-level audit record detailing execution context for debugging and observability."""

    step_number: int
    agent_name: str
    input_data: dict[str, Any] = Field(default_factory=dict)
    output_data: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: float = 0.0
    status: str = "success"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AuditLog(BaseModel):
    """Complete run trace for post-mortem debugging and verification."""

    run_id: str
    query: str
    steps: list[StepTrace] = Field(default_factory=list)
    total_token_usage: TokenUsage = Field(default_factory=TokenUsage)
    total_latency_ms: float = 0.0
    status: str = "completed"
    error: str | None = None
