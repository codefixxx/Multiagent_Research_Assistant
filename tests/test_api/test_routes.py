"""Integration tests for FastAPI endpoints."""

import pytest
from fastapi.testclient import TestClient

from src.api.job_runner import job_service
from src.api.main import app


@pytest.fixture(autouse=True)
def setup_mock_service(mock_llm):
    """Ensure job service uses the mock chat model during API tests."""
    job_service.default_llm = mock_llm


def test_health_check_endpoint():
    """GET /health must return operational status."""
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "redis_connected" in data


def test_root_overview_endpoint():
    """GET / must return API summary and documentation links."""
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "operational"
        assert "/docs" in data["docs_url"]


def test_submit_research_endpoint_success():
    """POST /research accepts valid query and returns HTTP 202 with run_id."""
    with TestClient(app) as client:
        payload = {"query": "Analyze modern vector databases for AI agents"}
        response = client.post("/research", json=payload)
        assert response.status_code == 202
        data = response.json()
        assert "run_id" in data
        assert data["status"] == "queued"
        assert len(data["run_id"]) > 10


def test_submit_research_validation_error():
    """POST /research rejects queries that are too short."""
    with TestClient(app) as client:
        payload = {"query": "ab"}  # min_length is 3
        response = client.post("/research", json=payload)
        assert response.status_code == 422


def test_get_research_status_not_found():
    """GET /research/{id} returns 404 for non-existent run ID."""
    with TestClient(app) as client:
        response = client.get("/research/non-existent-uuid-12345")
        assert response.status_code == 404


def test_get_research_trace_not_found():
    """GET /research/{id}/trace returns 404 for unknown run."""
    with TestClient(app) as client:
        response = client.get("/research/unknown-run-id-999/trace")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_full_api_workflow_end_to_end(mock_llm):
    """End-to-end test submitting a research job, polling status, and streaming events."""
    import httpx

    job_service.default_llm = mock_llm

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
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
async def test_stream_endpoint_returns_sse_stream(mock_llm):
    """GET /research/{id}/stream streams real-time Server-Sent Events."""
    import httpx

    job_service.default_llm = mock_llm

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
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


def test_cancel_non_running_job_returns_400():
    """POST /research/{id}/cancel returns 400 when job is not actively running."""
    with TestClient(app) as client:
        response = client.post("/research/not-running-id-404/cancel")
        assert response.status_code == 400
