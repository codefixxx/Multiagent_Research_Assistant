"""Live multi-agent graph execution test runner.

Runs the complete LangGraph state machine with the Supervisor, Planner,
Researcher, Reviewer, and Writer live against Groq or Gemini.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure UTF-8 stdout on Windows console
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        getattr(sys.stdout, "reconfigure")(encoding="utf-8")
    except Exception:
        pass

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(override=True)

from src.config import settings  # noqa: E402
from src.core.llm import get_chat_model  # noqa: E402
from src.graph.builder import compile_research_graph, create_initial_state  # noqa: E402


async def main(provider: str, model: str | None, query: str):
    print("=" * 70)
    print(f"  RUNNING LANGGRAPH SUPERVISOR STATE MACHINE (LIVE PROVIDER: {provider.upper()})")
    print("=" * 70)

    try:
        llm = get_chat_model(provider=provider, model_name=model)
    except Exception as e:
        print(f"[FAIL] Error configuring LLM provider '{provider}': {e}")
        sys.exit(1)

    # Initialize clean graph state
    initial_state = create_initial_state(query=query)
    graph = compile_research_graph(llm=llm)

    print(f"\n[QUERY] '{query}'")
    print(f"[RUN ID] {initial_state.get('run_id')}")
    print("\n--- STREAMING GRAPH NODE TRANSITIONS ---\n")

    # Stream state updates node-by-node
    final_state = initial_state
    async for event in graph.astream(initial_state):
        for node_name, node_output in event.items():
            final_state.update(node_output)
            step_num = final_state.get("step_count", 0)

            if node_name == "planner":
                plan = final_state.get("plan")
                sub_qs = plan.sub_questions if plan else []
                print(f"[STEP {step_num}] PLANNER COMPLETED")
                print(f"         Decomposed into {len(sub_qs)} sub-questions:")
                for sq in sub_qs:
                    print(f"           - [{sq.id}] {sq.question}")

            elif node_name == "researcher":
                cur_idx = final_state.get("current_sub_question_index", 0)
                plan = final_state.get("plan")
                sq_id = (
                    plan.sub_questions[cur_idx].id
                    if plan and cur_idx < len(plan.sub_questions)
                    else "unknown"
                )
                cur_findings = final_state.get("current_sub_question_findings", [])
                rev = final_state.get("revision_count", 0)
                is_rev = "(Revision Pass)" if rev > 0 else "(First Pass)"
                print(f"[STEP {step_num}] RESEARCHER COMPLETED {is_rev}")
                print(f"         Sub-Question: {sq_id} | Extracted {len(cur_findings)} findings")

            elif node_name == "reviewer":
                cur_idx = final_state.get("current_sub_question_index", 0)
                rev = final_state.get("revision_count", 0)
                feedback = final_state.get("review_feedback")
                print(f"[STEP {step_num}] REVIEWER EVALUATION")
                if feedback and rev > 0:
                    print("         Decision: REVISION REQUESTED (Pass 1 of 1 allowed)")
                    print(f"         Feedback: {feedback}")
                else:
                    print("         Decision: APPROVED (Advancing to next step)")

            elif node_name == "writer":
                report = final_state.get("report")
                print(f"[STEP {step_num}] WRITER SYNTHESIS COMPLETED")
                if report:
                    print(f"         Title: {report.title}")
                    print(
                        f"         Sections: {len(report.sections)} | Citations: {len(report.citations)}"
                    )

            elif node_name == "emergency_writer":
                print(f"[STEP {step_num}] EMERGENCY WRITER COMPLETED (Budget limit triggered)")

    print("\n" + "=" * 70)
    print("  RESEARCH RUN COMPLETE - AUDIT TRAIL & TELEMETRY")
    print("=" * 70)

    # Telemetry and Budget Summary
    total_tokens = final_state.get("total_tokens")
    token_count = total_tokens.total_tokens if total_tokens else 0
    traces = final_state.get("audit_traces", [])

    status_val = str(final_state.get("status") or "unknown").upper()
    print(f"\nStatus: {status_val}")
    print(f"Total Steps Executed: {len(traces)}")
    print(f"Cumulative Tokens: {token_count:,}")

    print("\n--- STEP-LEVEL AUDIT TRACE ---")
    for t in traces:
        print(
            f"  Step {t.step_number} | Agent: {t.agent_name:<16} | Latency: {t.latency_ms:>7.1f}ms | Tokens: {t.token_usage.total_tokens:>5}"
        )

    report = final_state.get("report")
    if report and report.markdown_output:
        print("\n--- FINAL SYNTHESIZED REPORT ---")
        print(report.markdown_output)

    print(f"\n[DONE] Graph execution completed successfully with {provider.upper()}!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live LangGraph multi-agent research runner")
    parser.add_argument(
        "--provider",
        choices=["groq", "gemini", "mock"],
        default=settings.LLM_PROVIDER,
        help="LLM Provider to use (default: settings.LLM_PROVIDER)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model override (e.g. qwen/qwen3.8-27b or gemini-3.5-flash)",
    )
    parser.add_argument(
        "--query",
        default="Compare Redis vs Memcached latency and persistence architectures",
        help="Research query to execute",
    )
    args = parser.parse_args()
    asyncio.run(main(provider=args.provider, model=args.model, query=args.query))
