"""Integration tests for FastAPI endpoints."""

import httpx
import pytest

from src.api.job_runner import job_service
from src.api.main import app


@pytest.fixture(autouse=True)
async def setup_mock_service(mock_llm):
    """Ensure job service uses the mock chat model during API tests."""
    job_service.default_llm = mock_llm
    await job_service.initialize(force_new=True, force_fake=True)
    yield
    job_service.default_llm = None


@pytest.fixture
async def client():
    """Async HTTP test client bound to the FastAPI ASGI application."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health_check_endpoint(client):
    """GET /health must return operational status."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "redis_connected" in data


@pytest.mark.asyncio
async def test_root_overview_endpoint(client):
    """GET / must return API summary and documentation links."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "operational"
    assert "/docs" in data["docs_url"]


@pytest.mark.asyncio
async def test_submit_research_endpoint_success(client):
    """POST /research accepts valid query and returns HTTP 202 with run_id."""
    payload = {"query": "Analyze modern vector databases for AI agents"}
    response = await client.post("/research", json=payload)
    assert response.status_code == 202
    data = response.json()
    assert "run_id" in data
    assert data["status"] == "queued"
    assert len(data["run_id"]) > 10


@pytest.mark.asyncio
async def test_submit_research_validation_error(client):
    """POST /research rejects queries that are too short."""
    payload = {"query": "ab"}  # min_length is 3
    response = await client.post("/research", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_research_status_not_found(client):
    """GET /research/{id} returns 404 for non-existent run ID."""
    response = await client.get("/research/non-existent-uuid-12345")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_research_trace_not_found(client):
    """GET /research/{id}/trace returns 404 for unknown run."""
    response = await client.get("/research/unknown-run-id-999/trace")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_full_api_workflow_end_to_end(client):
    """End-to-end test submitting a research job, polling status, and streaming events."""
    # 1. Submit research
    post_resp = await client.post(
        "/research",
        json={"query": "Evaluate distributed cache invalidation strategies"},
    )
    assert post_resp.status_code == 202
    run_id = post_resp.json()["run_id"]

    # 2. Wait for background execution to complete
    task = job_service._active_tasks.get(run_id)
    if task:
        await task

    # 3. Poll status
    status_resp = await client.get(f"/research/{run_id}")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["run_id"] == run_id
    assert status_data["status"] == "completed"
    assert status_data["report"] is not None
    assert status_data["progress_pct"] == 100

    # 4. Fetch trace
    trace_resp = await client.get(f"/research/{run_id}/trace")
    assert trace_resp.status_code == 200
    trace_data = trace_resp.json()
    assert trace_data["run_id"] == run_id
    assert trace_data["step_count"] >= 1


@pytest.mark.asyncio
async def test_stream_endpoint_returns_sse_stream(client):
    """GET /research/{id}/stream streams real-time Server-Sent Events."""
    # Submit research job
    post_resp = await client.post(
        "/research",
        json={"query": "Test query for SSE stream verification"},
    )
    assert post_resp.status_code == 202
    run_id = post_resp.json()["run_id"]

    # Stream lines
    stream_chunks: list[str] = []
    async with client.stream("GET", f"/research/{run_id}/stream") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        async for line in response.aiter_lines():
            if line:
                stream_chunks.append(line)
            if any("job_completed" in c or "job_failed" in c for c in stream_chunks):
                break

    all_stream_text = "\n".join(stream_chunks)
    assert "event:" in all_stream_text
    assert "data:" in all_stream_text


@pytest.mark.asyncio
async def test_cancel_non_running_job_returns_400(client):
    """POST /research/{id}/cancel returns 400 when job is not actively running."""
    response = await client.post("/research/not-running-id-404/cancel")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_dashboard_endpoint(client):
    """GET /dashboard and /ui return 200 with HTML content."""
    resp = await client.get("/dashboard")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "RESEARCH ENGINE" in resp.text

    alias_resp = await client.get("/ui")
    assert alias_resp.status_code == 200
    assert "text/html" in alias_resp.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_static_asset_endpoint(client):
    """GET /static/styles.css returns CSS styles."""
    resp = await client.get("/static/styles.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers.get("content-type", "")
    assert "--bg-void" in resp.text


@pytest.mark.asyncio
async def test_submit_research_with_byok_and_model_matrix(client):
    """POST /research accepts optional model_matrix and api_keys."""
    payload = {
        "query": "Compare LanceDB and Chroma for agentic memory",
        "max_sub_questions": 2,
        "model_matrix": {
            "planner": "gemini-2.5-flash",
            "researcher": "gemini-3.5-flash-lite",
            "reviewer": "gemini-2.5-flash",
            "writer": "gemini-2.5-flash",
        },
        "api_keys": {
            "gemini": "AIzaSyMockKeyForTesting123456",
            "tavily": "tvly-mock-key-testing",
        },
    }
    response = await client.post("/research", json=payload)
    assert response.status_code == 202
    data = response.json()
    assert "run_id" in data
    assert data["status"] == "queued"


@pytest.mark.asyncio
async def test_get_research_history_endpoint(client):
    """GET /research/history returns paginated historical runs in reverse chronological order."""
    # 1. Initial check on history
    initial_res = await client.get("/research/history")
    assert initial_res.status_code == 200
    initial_data = initial_res.json()
    assert "total" in initial_data
    assert "runs" in initial_data
    assert isinstance(initial_data["runs"], list)

    # 2. Submit a new research run
    query_text = "Historical Run Indexing Verification Test"
    submit_res = await client.post("/research", json={"query": query_text})
    assert submit_res.status_code == 202
    run_id = submit_res.json()["run_id"]

    # 3. Query history again
    history_res = await client.get("/research/history?limit=10&offset=0")
    assert history_res.status_code == 200
    history_data = history_res.json()
    assert history_data["total"] >= 1
    found = [r for r in history_data["runs"] if r["run_id"] == run_id]
    assert len(found) == 1
    item = found[0]
    assert item["query"] == query_text
    assert "status" in item
    assert "has_report" in item
    assert item["has_report"] is False  # newly submitted run has no report yet


@pytest.mark.asyncio
async def test_steer_plan_endpoint(client, mock_llm):
    """POST /research/{run_id}/steer accepts human steering actions."""
    from src.api.job_runner import job_service

    await job_service.initialize()
    run_id = "test-hitl-steer-01"

    # 1. Initialize run in awaiting_approval status
    assert job_service.run_manager is not None
    await job_service.run_manager.init_run(
        run_id=run_id,
        query="Distributed Cache Consensus",
        hitl_enabled=True,
    )
    await job_service.run_manager.update_run_status(
        run_id=run_id,
        status="awaiting_approval",
        current_node="plan_gate",
    )

    # 2. Test approve action
    approve_res = await client.post(
        f"/research/{run_id}/steer",
        json={"action": "approve"},
    )
    assert approve_res.status_code == 200
    approve_data = approve_res.json()
    assert approve_data["action"] == "approve"
    assert approve_data["status"] == "accepted"

    # 3. Test modify action with customized sub-questions
    modified_plan = {
        "objective": "Targeted Latency Investigation",
        "sub_questions": [
            {
                "id": "sq_custom_1",
                "question": "What is the P99 tail latency of Redis Cluster?",
                "rationale": "Empirical latency profile",
                "search_queries": ["Redis Cluster P99 tail latency benchmark"],
            }
        ],
    }
    modify_res = await client.post(
        f"/research/{run_id}/steer",
        json={"action": "modify", "modified_plan": modified_plan},
    )
    assert modify_res.status_code == 200
    modify_data = modify_res.json()
    assert modify_data["action"] == "modify"
    assert modify_data["status"] == "accepted"

    # 4. Non-existent run should return 400
    bad_res = await client.post(
        "/research/non-existent-run-999/steer",
        json={"action": "approve"},
    )
    assert bad_res.status_code == 400
