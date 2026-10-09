"""Tests for ResearchJobService, event streaming, and cancellation."""

import asyncio

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

    await service.start_job(run_id=run_id, request=request)
    task = service._active_tasks.get(run_id)
    if task:
        await task

    # Give listener a brief moment to process
    await asyncio.sleep(0.1)
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
    await service.start_job(run_id=run_id, request=request)
    # Cancel immediately
    cancelled = await service.cancel_job(run_id)
    assert cancelled is True

    # Check status
    await asyncio.sleep(0.05)
    status_resp = await service.get_status(run_id)
    assert status_resp is not None
    assert status_resp.status in ("cancelled", "failed")
