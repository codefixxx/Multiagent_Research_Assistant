"""Tests for ResearchJobService, event streaming, and cancellation."""

import asyncio
import uuid

import pytest

from src.api.events import EventBroadcaster
from src.api.job_runner import ResearchJobService
from src.schemas.api import ResearchRequest


@pytest.mark.asyncio
async def test_job_service_lifecycle_and_events(mock_llm):
    """Test background job execution dispatches expected lifecycle SSE events."""
    broadcaster = EventBroadcaster()
    service = ResearchJobService(event_broadcaster=broadcaster, llm=mock_llm)
    await service.initialize()

    run_id = "test-job-stream-123"
    request = ResearchRequest(query="Compare raft consensus vs paxos")

    events_received: list[str] = []

    async def _listen():
        async for msg in broadcaster.subscribe(run_id, heartbeat_interval=1.0):
            events_received.append(msg)
            if "event: job_completed" in msg or "event: job_failed" in msg:
                break

    listener_task = asyncio.create_task(_listen())

    await service.start_job(run_id=run_id, request=request, mode="embedded")
    task = service._active_tasks.get(run_id)
    if task:
        await task

    # Wait for listener to receive completion event
    try:
        await asyncio.wait_for(listener_task, timeout=5.0)
    except (TimeoutError, asyncio.CancelledError):
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass

    # Verify event types received
    all_events_text = "".join(events_received)
    assert "event: job_queued" in all_events_text
    assert "event: job_started" in all_events_text
    assert "event: planner_completed" in all_events_text
    assert "event: job_completed" in all_events_text


@pytest.mark.asyncio
async def test_job_service_cancellation(mock_llm):
    """Cancelling a running job must update status and emit failure event."""
    broadcaster = EventBroadcaster()
    service = ResearchJobService(event_broadcaster=broadcaster, llm=mock_llm)
    await service.initialize()

    run_id = "test-cancel-run-99"
    request = ResearchRequest(query="Test query for cancellation")

    # Start job
    await service.start_job(run_id=run_id, request=request, mode="embedded")
    # Cancel immediately
    cancelled = await service.cancel_job(run_id)
    assert cancelled is True

    # Check status
    await asyncio.sleep(0.05)
    status_resp = await service.get_status(run_id)
    assert status_resp is not None
    assert status_resp.status in ("cancelled", "failed")


@pytest.mark.asyncio
async def test_job_service_hitl_reject_cancellation(mock_llm):
    """Rejecting a plan during HITL should cleanly mark run as cancelled without errors or RAG score."""
    broadcaster = EventBroadcaster()
    service = ResearchJobService(event_broadcaster=broadcaster, llm=mock_llm)
    await service.initialize()

    run_id = f"test-hitl-reject-{uuid.uuid4().hex[:8]}"
    request = ResearchRequest(query="Test HITL cancellation", hitl_enabled=True)

    events_received: list[str] = []

    async def _listen():
        async for msg in broadcaster.subscribe(run_id, heartbeat_interval=0.5):
            events_received.append(msg)
            if "event: job_cancelled" in msg:
                break

    listener_task = asyncio.create_task(_listen())

    # Start job with HITL
    await service.start_job(run_id=run_id, request=request, mode="embedded")

    # Wait for the job to pause at plan_gate / awaiting_approval
    for _ in range(50):
        if run_id in service._plan_approval_events:
            break
        await asyncio.sleep(0.05)

    # Submit plan rejection
    decision_submitted = await service.submit_plan_decision(run_id=run_id, action="reject")
    assert decision_submitted is True

    # Wait for job task to conclude
    task = service._active_tasks.get(run_id)
    if task:
        await task

    try:
        await asyncio.wait_for(listener_task, timeout=3.0)
    except (TimeoutError, asyncio.CancelledError):
        listener_task.cancel()

    status_resp = await service.get_status(run_id)
    assert status_resp is not None
    assert status_resp.status == "cancelled"
    assert status_resp.error_message is None
    assert status_resp.rag_score is None

    all_events = "".join(events_received)
    assert "event: job_cancelled" in all_events
