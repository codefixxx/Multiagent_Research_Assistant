"""Complete end-to-end live workflow test script without mocks.

Tests the full production stack:
1. Live Redis server on localhost:6379
2. Live LLM (Gemini / Groq)
3. Live Tavily Web Search & Scraper
4. Live LangGraph Supervisor Orchestration
5. Live Pre-flight Citation Validation
6. Live Server-Sent Events (SSE) streaming
7. Real-time Redis state checkpointer and audit log verification
"""

import asyncio
import json
import sys
import time
from pathlib import Path

# Ensure UTF-8 output on Windows
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        getattr(sys.stdout, "reconfigure")(encoding="utf-8")
    except Exception:
        pass

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(override=True)

from src.api.events import broadcaster
from src.api.job_runner import job_service
from src.config import settings
from src.core.llm import get_chat_model
from src.persistence.redis_saver import get_redis_client
from src.schemas.api import ResearchRequest


async def main():
    print("=" * 80)
    print("  PRODUCTION-GRADE MULTI-AGENT RESEARCH ASSISTANT")
    print("  COMPREHENSIVE LIVE WORKFLOW TEST (NO MOCKS)")
    print("=" * 80)

    # 1. Verify Live Redis Connection
    print("\n[1/5] Verifying Live Redis TCP Connection...")
    client = await get_redis_client()
    pong = await client.ping()
    print(f"      Redis Ping Result: {pong} (Server: {settings.REDIS_URL})")
    assert pong is True, "Failed connecting to Redis!"

    # 2. Verify Live LLM Provider
    print(f"\n[2/5] Initializing Live LLM Provider ({settings.LLM_PROVIDER.upper()})...")
    llm = get_chat_model()
    print(f"      Model configured: {settings.GEMINI_MODEL if settings.LLM_PROVIDER == 'gemini' else settings.GROQ_MODEL}")

    # 3. Initialize Background Job Service with Live Components
    print("\n[3/5] Initializing FastAPI Background Job Engine...")
    job_service.default_llm = llm
    await job_service.initialize()

    run_id = f"live-test-{int(time.time())}"
    query = "Compare Redis vs Memcached latency and threading models"
    request = ResearchRequest(
        query=query,
        max_sub_questions=2,
        deep_scrape=True,
    )
    print(f"      Dispatched Run ID: {run_id}")
    print(f"      Query: '{query}'")

    # 4. Stream Server-Sent Events (SSE) in Real Time
    print("\n[4/5] Starting Background Research Run & Streaming SSE Events...\n")

    events_captured = []

    async def _stream_listener():
        async for sse_chunk in broadcaster.subscribe(run_id, heartbeat_interval=5.0):
            events_captured.append(sse_chunk)
            lines = [line.strip() for line in sse_chunk.split("\n") if line.strip()]
            event_name = "unknown"
            event_data = {}
            for line in lines:
                if line.startswith("event:"):
                    event_name = line.replace("event:", "").strip()
                elif line.startswith("data:"):
                    try:
                        event_data = json.loads(line.replace("data:", "").strip())
                    except Exception:
                        pass
            
            # Print formatted event
            if event_name not in ("unknown", "ping") and event_data:
                print(f"  >>> [SSE EVENT] {event_name.upper()}")
                for k, v in event_data.items():
                    if k not in ("run_id", "timestamp", "event"):
                        val_str = str(v)
                        if len(val_str) > 120:
                            val_str = val_str[:117] + "..."
                        print(f"        {k}: {val_str}")
                print()

            if event_name in ("job_completed", "job_failed", "budget_exceeded"):
                break

    # Launch SSE listener concurrently
    listener_task = asyncio.create_task(_stream_listener())

    # Launch Job in Job Service
    await job_service.start_job(run_id=run_id, request=request, llm_override=llm)

    # Wait for completion
    worker_task = job_service._active_tasks.get(run_id)
    if worker_task:
        await worker_task

    await listener_task

    # 5. Verify Results, Pre-flight Citations, and Redis Checkpoints
    print("\n[5/5] Inspecting Persisted State, Reports, and Audit Traces...")

    # Fetch status from API service
    status = await job_service.get_status(run_id)
    assert status is not None
    print(f"      Final Run Status: {status.status}")
    print(f"      Progress: {status.progress_pct}%")
    print(f"      Step Count: {status.step_count}")
    print(f"      Total Tokens Consumed: {status.total_tokens:,}")

    # Inspect Report
    report = status.report
    assert report is not None, "Report was not generated!"
    print(f"\n      Report Title: '{report.title}'")
    print(f"      Executive Summary: {report.executive_summary[:200]}...")
    print(f"      Sections Generated: {len(report.sections)}")
    for i, sec in enumerate(report.sections, 1):
        print(f"        Section {i}: {sec.title} (Citations: {sec.citation_ids})")
    print(f"      Citations Verified: {len(report.citations)}")
    for cite in report.citations:
        print(f"        - {cite.citation_id}: {cite.source_url} -> '{cite.verified_claim[:80]}...'")

    # Fetch Audit Trace
    trace = await job_service.get_audit_trace(run_id)
    assert trace is not None
    print(f"\n      Audit Trace Steps Recorded: {len(trace.steps)}")
    for st in trace.steps:
        print(f"        Step {st.step_number}: Agent={st.agent_name:<16} Latency={st.latency_ms:.1f}ms Tokens={st.token_usage.total_tokens}")

    # Verify direct Redis Keys
    raw_meta = await client.get(f"research:run:{run_id}:metadata")
    raw_report = await client.get(f"research:run:{run_id}:report")
    raw_trace = await client.get(f"research:run:{run_id}:trace")
    assert raw_meta is not None, "Redis metadata missing!"
    assert raw_report is not None, "Redis report missing!"
    assert raw_trace is not None, "Redis trace missing!"

    print("\n      Redis State Verification: ALL KEYS PERSISTED IN REDIS")
    print(f"        [OK] research:run:{run_id}:metadata ({len(raw_meta)} bytes)")
    print(f"        [OK] research:run:{run_id}:report   ({len(raw_report)} bytes)")
    print(f"        [OK] research:run:{run_id}:trace    ({len(raw_trace)} bytes)")

    print("\n" + "=" * 80)
    print("  LIVE MULTI-AGENT WORKFLOW TEST COMPLETED SUCCESSFULLY!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
