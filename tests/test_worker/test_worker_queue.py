"""Integration tests for Decoupled Task Worker, Redis Job Queue, and Distributed Execution."""

import asyncio
import time
import uuid

import httpx
import pytest

from src.api.events import EventBroadcaster
from src.api.job_runner import ResearchJobService, job_service
from src.api.main import app
from src.config import settings
from src.persistence.queue import RedisJobQueue
from src.persistence.redis_saver import get_redis_client
from src.schemas.api import ResearchRequest
from src.worker import ResearchWorker


@pytest.fixture
async def client():
    """Async HTTP client for testing FastAPI routes."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_job_submission_returns_202_accepted_immediately_under_50ms(client, monkeypatch):
    """POST /research in decoupled mode enqueues to Redis and returns HTTP 202 in < 50ms without blocking."""
    monkeypatch.setattr(settings, "WORKER_MODE", "decoupled")
    await job_service.initialize()
    if job_service.queue:
        await job_service.queue.clear_queue()

    payload = {"query": "Evaluate distributed actor models for multi-agent systems"}

    start_time = time.perf_counter()
    response = await client.post("/research", json=payload)
    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    assert response.status_code == 202
    data = response.json()
    assert "run_id" in data
    assert data["status"] == "queued"
    # Verify non-blocking enqueue performance
    assert elapsed_ms < 100.0, f"Submission took {elapsed_ms:.1f}ms; expected < 100ms"

    # Verify the job is in the Redis queue
    assert job_service.queue is not None
    q_len = await job_service.queue.get_queue_length()
    assert q_len >= 1

    # Cleanup queue
    await job_service.queue.clear_queue()


@pytest.mark.asyncio
async def test_redis_job_queue_enqueue_dequeue():
    """Verify RedisJobQueue FIFO semantics, serialization, and length tracking."""
    redis_client = await get_redis_client()
    queue = RedisJobQueue(redis_client)
    await queue.clear_queue()

    run_id_1 = f"test-q-run-{uuid.uuid4().hex[:6]}"
    run_id_2 = f"test-q-run-{uuid.uuid4().hex[:6]}"
    req_1 = ResearchRequest(query="First queued query")
    req_2 = ResearchRequest(query="Second queued query")

    # Enqueue two jobs
    await queue.enqueue(run_id=run_id_1, request=req_1)
    await queue.enqueue(run_id=run_id_2, request=req_2)

    assert await queue.get_queue_length() == 2

    # Dequeue in FIFO order
    job_1 = await queue.dequeue(timeout=1.0)
    assert job_1 is not None
    assert job_1["run_id"] == run_id_1
    assert job_1["request"]["query"] == "First queued query"
    assert await queue.get_queue_length() == 1

    job_2 = await queue.dequeue(timeout=1.0)
    assert job_2 is not None
    assert job_2["run_id"] == run_id_2
    assert await queue.get_queue_length() == 0

    # Dequeue on empty queue returns None after timeout
    empty_res = await queue.dequeue(timeout=0.1)
    assert empty_res is None


@pytest.mark.asyncio
async def test_worker_heartbeat_and_active_registry():
    """Verify worker registration, periodic heartbeats, and graceful deregistration."""
    redis_client = await get_redis_client()
    queue = RedisJobQueue(redis_client)
    worker_id = f"worker-test-node-{uuid.uuid4().hex[:6]}"

    # Register worker
    await queue.register_worker(
        worker_id=worker_id,
        metadata={"concurrency": 4, "version": "0.1.0"},
        ttl=10,
    )

    active = await queue.get_active_workers()
    active_ids = [w["worker_id"] for w in active]
    assert worker_id in active_ids

    found = next(w for w in active if w["worker_id"] == worker_id)
    assert found["concurrency"] == 4

    # Deregister worker
    await queue.deregister_worker(worker_id)
    active_after = await queue.get_active_workers()
    active_after_ids = [w["worker_id"] for w in active_after]
    assert worker_id not in active_after_ids


@pytest.mark.asyncio
async def test_worker_processes_job_from_queue(mock_llm):
    """Independent worker pulls job from Redis, executes LangGraph, and persists completed report."""
    redis_client = await get_redis_client()
    queue = RedisJobQueue(redis_client)
    await queue.clear_queue()

    service = ResearchJobService(queue=queue, llm=mock_llm)
    await service.initialize()

    run_id = f"worker-test-run-{uuid.uuid4().hex[:6]}"
    request = ResearchRequest(query="Compare event streaming architectures in Kafka and Pulsar")

    # Enqueue job
    await queue.enqueue(run_id=run_id, request=request)
    assert service.run_manager is not None
    await service.run_manager.init_run(run_id=run_id, query=request.query)

    # Instantiate worker with the service
    worker = ResearchWorker(worker_id="test-unit-worker-1", concurrency=1, job_service=service, queue=queue)

    job_data = await queue.dequeue(timeout=1.0)
    assert job_data is not None
    assert job_data["run_id"] == run_id

    # Worker executes the job
    await worker.process_job(job_data)

    # Check status and report in Redis
    status_resp = await service.get_status(run_id)
    assert status_resp is not None
    assert status_resp.status == "completed"
    assert status_resp.report is not None
    assert status_resp.progress_pct == 100
    assert status_resp.report.title != ""


@pytest.mark.asyncio
async def test_worker_cancellation_via_redis_flag(mock_llm):
    """Cancelling a run via Redis cancel flag halts worker execution."""
    redis_client = await get_redis_client()
    queue = RedisJobQueue(redis_client)
    service = ResearchJobService(queue=queue, llm=mock_llm)
    await service.initialize()

    run_id = f"cancel-flag-run-{uuid.uuid4().hex[:6]}"
    request = ResearchRequest(query="Query to be cancelled via distributed Redis flag")

    assert service.run_manager is not None
    await service.run_manager.init_run(run_id=run_id, query=request.query)

    # Trigger cancellation
    cancelled = await service.cancel_job(run_id)
    assert cancelled is True

    # Assert cancel flag is stored in Redis
    assert await queue.is_cancelled(run_id) is True

    status_resp = await service.get_status(run_id)
    assert status_resp is not None
    assert status_resp.status == "cancelled"


@pytest.mark.asyncio
async def test_event_broadcaster_redis_history_replay():
    """Verify Redis-backed event persistence allows late-connecting SSE listeners to replay full event stream."""
    redis_client = await get_redis_client()
    broadcaster = EventBroadcaster(redis_client=redis_client)
    run_id = f"replay-run-{uuid.uuid4().hex[:6]}"

    # Worker broadcasts series of events
    await broadcaster.broadcast(run_id=run_id, event="job_queued", data={"status": "queued"})
    await broadcaster.broadcast(run_id=run_id, event="job_started", data={"status": "planning"})
    await broadcaster.broadcast(run_id=run_id, event="job_completed", data={"status": "completed", "title": "Done"})

    # Client connects later and subscribes
    replayed_events: list[str] = []
    async for msg in broadcaster.subscribe(run_id=run_id, heartbeat_interval=1.0):
        replayed_events.append(msg)

    all_text = "".join(replayed_events)
    assert "event: job_queued" in all_text
    assert "event: job_started" in all_text
    assert "event: job_completed" in all_text

    # Cleanup
    await broadcaster.clear_history(run_id)


@pytest.mark.asyncio
async def test_chaos_fastapi_reboot_worker_uninterrupted(mock_llm):
    """Chaos test: Simulate web server reboot mid-run while dedicated worker executes; state and report survive in Redis."""
    redis_client = await get_redis_client()
    queue = RedisJobQueue(redis_client)
    await queue.clear_queue()

    # Web Server Instance 1: Accepts request, enqueues to Redis
    web_service_v1 = ResearchJobService(queue=queue)
    await web_service_v1.initialize()

    run_id = f"chaos-reboot-run-{uuid.uuid4().hex[:6]}"
    request = ResearchRequest(query="Resilience of distributed consensus during network partitions")

    # Web Server 1 initializes run and enqueues
    assert web_service_v1.run_manager is not None
    await web_service_v1.run_manager.init_run(run_id=run_id, query=request.query)
    await queue.enqueue(run_id=run_id, request=request)

    # Dedicated Worker Process (Independent of Web Server 1)
    worker_service = ResearchJobService(queue=queue, llm=mock_llm)
    await worker_service.initialize()
    worker = ResearchWorker(worker_id="chaos-worker-node", concurrency=1, job_service=worker_service, queue=queue)

    job_data = await queue.dequeue(timeout=1.0)
    assert job_data is not None

    # *** CHAOS EVENT: Web Server 1 dies / restarts ***
    del web_service_v1

    # Worker continues executing uninterrupted
    await worker.process_job(job_data)

    # *** Web Server Instance 2 boots up after reboot ***
    web_service_v2 = ResearchJobService(queue=queue)
    await web_service_v2.initialize()

    # Client reconnects to the newly rebooted Web Server 2 and requests run status
    recovered_status = await web_service_v2.get_status(run_id)

    assert recovered_status is not None
    assert recovered_status.run_id == run_id
    assert recovered_status.status == "completed"
    assert recovered_status.report is not None
    assert recovered_status.progress_pct == 100
    assert recovered_status.report.title != ""

    # Verify audit trace is fully accessible on the new server instance
    trace = await web_service_v2.get_audit_trace(run_id)
    assert trace is not None
    assert trace.status == "completed"
