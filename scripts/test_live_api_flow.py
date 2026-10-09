"""Live End-to-End API Flow Test.

Submits a live research query to the containerized FastAPI service,
monitors real-time progress across parallel researcher nodes,
and retrieves the finalized structured report and citation validation.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

# Configure UTF-8 output on Windows
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        getattr(sys.stdout, "reconfigure")(encoding="utf-8")
    except Exception:
        pass

import httpx

BASE_URL = "http://localhost:8000"
TEST_QUERY = "Compare LanceDB vs Chroma for local-first vector search in AI agent workflows"


async def main():
    print("=" * 80)
    print("  PRODUCTION MULTI-AGENT SYSTEM - LIVE HTTP FLOW TEST")
    print(f"  Target: {BASE_URL}")
    print(f"  Query:  {TEST_QUERY}")
    print("=" * 80)

    async with httpx.AsyncClient(timeout=120.0) as client:
        # 1. Health Check
        print("\n[Step 1] Checking Service Health...")
        health_resp = await client.get(f"{BASE_URL}/health")
        health_resp.raise_for_status()
        health_data = health_resp.json()
        print(f"  -> Health: {health_data}")
        assert health_data.get("status") == "healthy", "API not healthy!"
        assert health_data.get("redis_connected") is True, "Redis not connected!"

        # 2. Submit Research Query
        print("\n[Step 2] Submitting Research Job to POST /research...")
        payload = {
            "query": TEST_QUERY,
            "max_sub_questions": 2,
            "deep_scrape": True,
        }
        submit_resp = await client.post(f"{BASE_URL}/research", json=payload)
        submit_resp.raise_for_status()
        submit_data = submit_resp.json()
        run_id = submit_data["run_id"]
        print(f"  -> HTTP {submit_resp.status_code} Accepted")
        print(f"  -> Run ID: {run_id}")
        print(f"  -> Initial Status: {submit_data.get('status')}")

        # 3. Poll Real-Time Execution Status
        print("\n[Step 3] Polling Job Progress (GET /research/{run_id})...")
        start_time = time.time()
        last_node = None
        final_status = None

        while True:
            elapsed = time.time() - start_time
            if elapsed > 180:
                raise TimeoutError("Test timed out after 180 seconds!")

            status_resp = await client.get(f"{BASE_URL}/research/{run_id}")
            status_resp.raise_for_status()
            status_data = status_resp.json()

            current_status = status_data.get("status")
            current_node = status_data.get("current_node")
            progress_pct = status_data.get("progress_pct", 0)
            findings_count = status_data.get("findings_count", 0)
            total_tokens = status_data.get("total_tokens", 0)
            step_count = status_data.get("step_count", 0)

            if current_node != last_node or current_status != "running":
                print(
                    f"  [{elapsed:5.1f}s] Status: {current_status:<10} | "
                    f"Node: {str(current_node):<15} | "
                    f"Progress: {progress_pct:>3}% | "
                    f"Findings: {findings_count:>2} | "
                    f"Tokens: {total_tokens:>5} | "
                    f"Steps: {step_count:>2}"
                )
                last_node = current_node

            if current_status in ("completed", "failed", "budget_exceeded"):
                final_status = status_data
                break

            await asyncio.sleep(2.0)

        total_elapsed = time.time() - start_time
        print(f"\n[Execution Completed in {total_elapsed:.1f}s with status: {final_status['status'].upper()}]")

        if final_status["status"] != "completed":
            print(f"ERROR DETAILS: {final_status.get('error_message')}")
            return

        # 4. Fetch Audit Trace
        print("\n[Step 4] Fetching Granular Audit Trace (GET /research/{run_id}/trace)...")
        trace_resp = await client.get(f"{BASE_URL}/research/{run_id}/trace")
        trace_resp.raise_for_status()
        trace_data = trace_resp.json()
        print(f"  -> Total Steps in Trace: {len(trace_data.get('steps', []))}")
        print(f"  -> Total Trace Tokens:   {trace_data.get('total_tokens', {})}")
        for i, step in enumerate(trace_data.get("steps", []), 1):
            agent = step.get("agent_name")
            action = step.get("action")
            latency = step.get("latency_ms", 0.0)
            print(f"     Step {i:02d}: [{agent}] -> {action} ({latency:.1f}ms)")

        # 5. Inspect Report and Citations
        report = final_status.get("report")
        citation_val = final_status.get("citation_validation")

        print("\n" + "=" * 80)
        print("  FINALIZED SYNTHESIZED RESEARCH REPORT")
        print("=" * 80)
        if report:
            print(f"\nTITLE: {report.get('title')}")
            print(f"\nEXECUTIVE SUMMARY:\n{report.get('executive_summary')}")

            sections = report.get("sections", [])
            print(f"\nSECTIONS GENERATED ({len(sections)}):")
            for sec in sections:
                print(f"\n### {sec.get('heading')}")
                content = sec.get("content", "")
                # Print first 250 chars of content
                preview = content[:300] + ("..." if len(content) > 300 else "")
                print(preview)

            print(f"\nKEY TAKEAWAYS:")
            for takeaway in report.get("key_takeaways", []):
                print(f"  * {takeaway}")

            print(f"\nREFERENCES ({len(report.get('references', []))}):")
            for ref in report.get("references", []):
                print(f"  [{ref.get('citation_key')}] {ref.get('title')} - {ref.get('url')}")

        print("\n" + "=" * 80)
        print("  CITATION VALIDATION METRICS")
        print("=" * 80)
        if citation_val:
            print(f"  Verified Citations:    {citation_val.get('verified_count', 0)}")
            print(f"  Total Citations:       {citation_val.get('total_citations', 0)}")
            print(f"  All Citations Valid:   {citation_val.get('all_valid', False)}")
            print(f"  Grounding Score:       {citation_val.get('grounding_score', 0.0):.2f}")
            failed = citation_val.get("failed_urls", [])
            if failed:
                print(f"  Failed / Inaccessible URLs: {failed}")

        # Save report markdown to a persistent artifact
        out_dir = Path("scripts")
        out_file = out_dir / f"live_report_{run_id[:8]}.json"
        out_file.write_text(json.dumps(final_status, indent=2), encoding="utf-8")
        print(f"\nFull report JSON saved to: {out_file.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
