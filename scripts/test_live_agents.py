"""CLI test runner to verify specialists with live LLM providers (Groq / Gemini)."""

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

# Ensure environment is loaded from .env
load_dotenv(override=True)

from src.agents.planner import plan_research  # noqa: E402
from src.agents.researcher import research_subquestion  # noqa: E402
from src.agents.writer import write_report  # noqa: E402
from src.config import settings  # noqa: E402
from src.core.llm import get_chat_model  # noqa: E402


async def main(provider: str, model: str | None, query: str):
    print(f"=== Testing Multi-Agent Specialists with Live Provider: {provider.upper()} ===")

    try:
        llm = get_chat_model(provider=provider, model_name=model)
    except Exception as e:
        print(f"[FAIL] Error configuring LLM provider '{provider}': {e}")
        print("Please ensure your API key is saved in the .env file.")
        sys.exit(1)

    print(f"\n1. [PLANNER] Generating research plan for: '{query}'...")
    try:
        plan, p_tokens, p_latency = await plan_research(query=query, llm=llm)
        print(f"   [OK] Planner succeeded in {p_latency:.1f}ms! (Tokens: {p_tokens.total_tokens})")
        print(f"   Objective: {plan.objective}")
        print(f"   Sub-Questions generated ({len(plan.sub_questions)}):")
        for sq in plan.sub_questions:
            print(f"     - [{sq.id}] {sq.question}")
            print(f"       Rationale: {sq.rationale}")
            print(f"       Queries: {sq.search_queries}")
    except Exception as e:
        print(f"[FAIL] Planner failed: {e}")
        sys.exit(1)

    first_sq = plan.sub_questions[0]
    print(f"\n2. [RESEARCHER] Investigating first sub-question: '{first_sq.question}'...")
    simulated_evidence = (
        "Source: https://example.com/research-findings-2024\n"
        "Evidence Excerpt: In benchmark tests, modern architectures demonstrated 40% latency improvements "
        "and 99.8% precision under continuous multi-agent workloads.\n"
    )

    try:
        research_out, r_tokens, r_latency = await research_subquestion(
            sub_question=first_sq,
            evidence_context=simulated_evidence,
            llm=llm,
        )
        print(
            f"   [OK] Researcher succeeded in {r_latency:.1f}ms! (Tokens: {r_tokens.total_tokens})"
        )
        print(f"   Is Answered: {research_out.is_answered}")
        print(f"   Summary: {research_out.summary}")
        print(f"   Findings extracted ({len(research_out.findings)}):")
        for f in research_out.findings:
            print(f"     - Claim: {f.claim}")
            print(f"       Source URL: {f.source_url}")
            print(f"       Snippet: {f.snippet}")
    except Exception as e:
        print(f"[FAIL] Researcher failed: {e}")
        sys.exit(1)

    print("\n3. [WRITER] Synthesizing research report with citations...")
    try:
        report, w_tokens, w_latency = await write_report(
            query=query,
            findings=research_out.findings,
            llm=llm,
        )
        print(f"   [OK] Writer succeeded in {w_latency:.1f}ms! (Tokens: {w_tokens.total_tokens})")
        print(f"   Report Title: {report.title}")
        print(f"   Executive Summary: {report.executive_summary}")
        print(f"   Sections: {len(report.sections)}, Citations: {len(report.citations)}")
        print("\n--- Compiled Markdown Output Preview ---")
        print(report.markdown_output[:500] + ("..." if len(report.markdown_output) > 500 else ""))
    except Exception as e:
        print(f"[FAIL] Writer failed: {e}")
        sys.exit(1)

    total_tokens = p_tokens.total_tokens + r_tokens.total_tokens + w_tokens.total_tokens
    print(
        f"\n[DONE] All 3 Specialists passed execution with {provider.upper()}! Total tokens: {total_tokens}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test specialists with live LLM provider")
    parser.add_argument(
        "--provider",
        choices=["groq", "gemini", "mock"],
        default=settings.LLM_PROVIDER,
        help="LLM Provider to use (default: settings.LLM_PROVIDER)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name (e.g. qwen/qwen3.8-27b or gemini-3.8-flash). Overrides .env setting.",
    )
    parser.add_argument(
        "--query",
        default="Compare Redis vs Memcached latency and persistence architectures",
        help="Research query to test",
    )
    args = parser.parse_args()
    asyncio.run(main(provider=args.provider, model=args.model, query=args.query))
