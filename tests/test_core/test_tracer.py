"""Unit tests for OpenTelemetry tracer provider, spans, and span indexer."""

import pytest
import asyncio
from src.core.tracer import (
    async_trace_span,
    sync_trace_span,
    get_run_spans,
    clear_run_spans,
    get_tracer,
)


@pytest.mark.asyncio
async def test_async_trace_span_lifecycle():
    run_id = "test-trace-run-001"
    clear_run_spans(run_id)

    async with async_trace_span("test_node", run_id=run_id, attributes={"role": "planner"}) as ctx:
        ctx["tokens_spent"] = 150
        ctx["model"] = "gemini-2.5-flash"
        await asyncio.sleep(0.01)

    spans = get_run_spans(run_id)
    assert len(spans) == 1
    span = spans[0]
    assert span["name"] == "test_node"
    assert span["run_id"] == run_id
    assert span["status"] == "success"
    assert span["error"] is None
    assert span["duration_ms"] > 0
    assert span["attributes"]["role"] == "planner"
    assert span["attributes"]["tokens_spent"] == 150
    assert span["attributes"]["model"] == "gemini-2.5-flash"

    clear_run_spans(run_id)
    assert len(get_run_spans(run_id)) == 0


@pytest.mark.asyncio
async def test_async_trace_span_error_handling():
    run_id = "test-trace-run-err"
    clear_run_spans(run_id)

    with pytest.raises(ValueError, match="Simulated agent failure"):
        async with async_trace_span("faulty_node", run_id=run_id, attributes={"step": 1}):
            raise ValueError("Simulated agent failure")

    spans = get_run_spans(run_id)
    assert len(spans) == 1
    span = spans[0]
    assert span["name"] == "faulty_node"
    assert span["status"] == "error"
    assert "Simulated agent failure" in span["error"]

    clear_run_spans(run_id)


def test_sync_trace_span():
    run_id = "test-sync-trace"
    clear_run_spans(run_id)

    with sync_trace_span("sync_tool_call", run_id=run_id, attributes={"tool": "tavily_search"}) as ctx:
        ctx["query"] = "quantum error correction"
        ctx["results_count"] = 5

    spans = get_run_spans(run_id)
    assert len(spans) == 1
    assert spans[0]["name"] == "sync_tool_call"
    assert spans[0]["attributes"]["tool"] == "tavily_search"
    assert spans[0]["attributes"]["query"] == "quantum error correction"
    assert spans[0]["attributes"]["results_count"] == 5

    clear_run_spans(run_id)
