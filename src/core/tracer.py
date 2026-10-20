"""OpenTelemetry distributed tracing engine for the multi-agent research supervisor."""

import os
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from typing import Any, AsyncIterator, Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode

from src.core.logger import logger

# Initialize singleton TracerProvider with standard multi-agent research service resource
_resource = Resource.create({"service.name": "multiagent-research-engine"})
_provider = TracerProvider(resource=_resource)
_exporter = InMemorySpanExporter()
_provider.add_span_processor(SimpleSpanProcessor(_exporter))
trace.set_tracer_provider(_provider)

_tracer = trace.get_tracer("multiagent-research-engine", "1.0.0")

# In-memory index of completed spans keyed by run_id
_run_spans_lock = threading.Lock()
_run_spans_store: dict[str, list[dict[str, Any]]] = {}


def get_tracer() -> trace.Tracer:
    """Return the global OpenTelemetry tracer instance."""
    return _tracer


def record_span(span_record: dict[str, Any]) -> None:
    """Register a finished span record under its associated run_id."""
    run_id = span_record.get("run_id") or span_record.get("attributes", {}).get("run_id")
    if not run_id:
        return
    with _run_spans_lock:
        if run_id not in _run_spans_store:
            _run_spans_store[run_id] = []
        _run_spans_store[run_id].append(span_record)


def get_run_spans(run_id: str) -> list[dict[str, Any]]:
    """Retrieve all recorded trace spans for a given run ID, ordered by start time."""
    with _run_spans_lock:
        spans = list(_run_spans_store.get(run_id, []))
    spans.sort(key=lambda s: s.get("start_time_epoch_ms", 0.0))
    return spans


def clear_run_spans(run_id: str) -> None:
    """Evict recorded spans for a finished or expired research run."""
    with _run_spans_lock:
        _run_spans_store.pop(run_id, None)


@asynccontextmanager
async def async_trace_span(
    name: str,
    run_id: str = "",
    attributes: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Async context manager to trace an agent execution node or tool invocation.

    Yields a mutable dictionary into which the caller can inject runtime
    attributes (e.g. token spend, sub-question count, tool output summary)
    before exiting the block.
    """
    start_time_ms = time.time() * 1000.0
    start_iso = datetime.now(UTC).isoformat()
    span_attrs = dict(attributes or {})
    if run_id:
        span_attrs["run_id"] = run_id

    dynamic_context: dict[str, Any] = {}
    error_msg: str | None = None
    status = "success"

    with _tracer.start_as_current_span(name) as otel_span:
        for k, v in span_attrs.items():
            if v is not None:
                otel_span.set_attribute(str(k), str(v) if not isinstance(v, (int, float, bool)) else v)

        span_id = hex(otel_span.get_span_context().span_id)
        parent_ctx = otel_span.parent
        parent_span_id = hex(parent_ctx.span_id) if parent_ctx and parent_ctx.span_id else None

        try:
            yield dynamic_context
            otel_span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            error_msg = str(exc)
            status = "error"
            otel_span.set_status(Status(StatusCode.ERROR, description=error_msg))
            otel_span.record_exception(exc)
            raise
        finally:
            end_time_ms = time.time() * 1000.0
            end_iso = datetime.now(UTC).isoformat()
            duration_ms = max(0.1, round(end_time_ms - start_time_ms, 2))

            # Merge dynamically attached attributes
            final_attrs = {**span_attrs, **dynamic_context}
            for k, v in dynamic_context.items():
                if v is not None:
                    otel_span.set_attribute(str(k), str(v) if not isinstance(v, (int, float, bool)) else v)

            span_record = {
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "name": name,
                "run_id": run_id,
                "start_time": start_iso,
                "end_time": end_iso,
                "start_time_epoch_ms": start_time_ms,
                "duration_ms": duration_ms,
                "status": status,
                "error": error_msg,
                "attributes": final_attrs,
            }
            record_span(span_record)


@contextmanager
def sync_trace_span(
    name: str,
    run_id: str = "",
    attributes: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Synchronous context manager counterpart for tool execution or sync blocks."""
    start_time_ms = time.time() * 1000.0
    start_iso = datetime.now(UTC).isoformat()
    span_attrs = dict(attributes or {})
    if run_id:
        span_attrs["run_id"] = run_id

    dynamic_context: dict[str, Any] = {}
    error_msg: str | None = None
    status = "success"

    with _tracer.start_as_current_span(name) as otel_span:
        for k, v in span_attrs.items():
            if v is not None:
                otel_span.set_attribute(str(k), str(v) if not isinstance(v, (int, float, bool)) else v)

        span_id = hex(otel_span.get_span_context().span_id)
        parent_ctx = otel_span.parent
        parent_span_id = hex(parent_ctx.span_id) if parent_ctx and parent_ctx.span_id else None

        try:
            yield dynamic_context
            otel_span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            error_msg = str(exc)
            status = "error"
            otel_span.set_status(Status(StatusCode.ERROR, description=error_msg))
            otel_span.record_exception(exc)
            raise
        finally:
            end_time_ms = time.time() * 1000.0
            end_iso = datetime.now(UTC).isoformat()
            duration_ms = max(0.1, round(end_time_ms - start_time_ms, 2))

            final_attrs = {**span_attrs, **dynamic_context}
            span_record = {
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "name": name,
                "run_id": run_id,
                "start_time": start_iso,
                "end_time": end_iso,
                "start_time_epoch_ms": start_time_ms,
                "duration_ms": duration_ms,
                "status": status,
                "error": error_msg,
                "attributes": final_attrs,
            }
            record_span(span_record)
