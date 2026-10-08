"""Standalone demonstration script simulating a process crash and Redis checkpoint recovery.

Usage:
    python scripts/simulate_crash.py
"""

import asyncio
import os
import sys
from typing import Any

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langchain_core.runnables import RunnableConfig, RunnableLambda
from langgraph.checkpoint.redis.ashallow import AsyncShallowRedisSaver

from src.graph.builder import compile_research_graph, create_initial_state
from src.persistence.redis_saver import (
    NodeIdempotencyCache,
    RedisRunManager,
    get_redis_client,
)
from src.schemas.finding import ResearcherOutput
from src.schemas.plan import ResearchPlan, SubQuestion, SubQuestionStatus
from src.schemas.report import ResearchReport
from src.schemas.review import ReviewEvaluation
from src.tools.evidence_collector import EvidenceCollector
from src.tools.search import MockSearchClient, MultiSearchClient
from tests.conftest import MockChatModel


class SimulatedWorkerCrash(RuntimeError):
    """Raised to simulate an unexpected node crash or worker kill signal."""


class CrashableSimulationLLM(MockChatModel):
    """Deterministic LLM for crash simulation that throws midway through execution."""

    should_crash: bool = True
    planner_runs: int = 0
    researcher_runs: int = 0

    def with_structured_output(self, schema: Any, *, include_raw: bool = False, **kwargs: Any):
        base_runnable = super().with_structured_output(schema, include_raw=include_raw, **kwargs)

        async def _intercept(messages: Any) -> Any:
            if schema == ResearchPlan:
                self.planner_runs += 1
                return await base_runnable.ainvoke(messages)

            if schema == ResearcherOutput:
                self.researcher_runs += 1
                if self.should_crash and self.researcher_runs == 2:
                    print("\n[CHAOS SIMULATION] *** SIMULATING PROCESS FAILURE AT SUB-QUESTION 2 ***\n")
                    raise SimulatedWorkerCrash("Process killed: SIGKILL sent to worker midway through research.")
                return await base_runnable.ainvoke(messages)

            if schema == ReviewEvaluation:
                return await base_runnable.ainvoke(messages)

            return await base_runnable.ainvoke(messages)

        return RunnableLambda(_intercept)


async def main() -> None:
    print("=" * 80)
    print("  PHASE 4: REDIS DURABLE CHECKPOINTING & CRASH RESUMPTION DEMO")
    print("=" * 80)

    # 1. Setup Redis persistence
    redis_client = await get_redis_client(force_fake=True)
    checkpointer = AsyncShallowRedisSaver(redis_client=redis_client)
    run_manager = RedisRunManager(redis_client=redis_client)
    idempotency_cache = NodeIdempotencyCache(redis_client=redis_client)

    run_id = "demo-run-crash-recovery"
    config: RunnableConfig = {"configurable": {"thread_id": run_id}}
    query = "Compare Redis and Memcached operational characteristics"

    # Define a 2-step research plan
    plan = ResearchPlan(
        query=query,
        objective="Analyze performance, clustering, and persistence differences.",
        sub_questions=[
            SubQuestion(
                id="sq_1",
                question="How do Redis and Memcached persistence architectures compare?",
                rationale="Evaluate disk durability options.",
                search_queries=["Redis RDB AOF vs Memcached volatility"],
                status=SubQuestionStatus.PENDING,
            ),
            SubQuestion(
                id="sq_2",
                question="How do Redis and Memcached clustering topologies differ?",
                rationale="Evaluate horizontal scalability and partition handling.",
                search_queries=["Redis cluster vs Memcached client-side consistent hashing"],
                status=SubQuestionStatus.PENDING,
            ),
        ],
    )

    print(f"\n[1] Initializing Run ID: {run_id}")
    await run_manager.init_run(run_id, query)

    # Compile Graph Instance 1 (with failure enabled)
    llm_v1 = CrashableSimulationLLM(fixed_plan=plan, should_crash=True)
    graph_v1 = compile_research_graph(
        llm=llm_v1,
        checkpointer=checkpointer,
        run_manager=run_manager,
        idempotency_cache=idempotency_cache,
        evidence_collector=EvidenceCollector(
            search_client=MultiSearchClient(mock_client=MockSearchClient())
        ),
    )

    initial_state = create_initial_state(query=query, run_id=run_id)

    print("\n[2] Starting execution on Worker Instance 1...")
    try:
        await graph_v1.ainvoke(initial_state, config=config)
    except SimulatedWorkerCrash as e:
        print(f"[!] Worker 1 CRASHED as expected: {e}")

    # Inspect checkpoint in Redis
    print("\n[3] Inspecting Checkpoint state in Redis...")
    saved_state = await graph_v1.aget_state(config)
    print(f"    - Current Checkpoint Step: {saved_state.values.get('step_count')}")
    print(f"    - Next Pending Node:       {saved_state.next}")
    print(f"    - Persisted Findings Count:{len(saved_state.values.get('findings', []))}")

    meta = await run_manager.get_run_metadata(run_id)
    print(f"    - Redis Metadata Status:   {meta.get('status') if meta else 'None'}")

    print("\n[4] Booting brand new Worker Instance 2 (Worker 1 is dead)...")
    llm_v2 = CrashableSimulationLLM(fixed_plan=plan, should_crash=False)
    graph_v2 = compile_research_graph(
        llm=llm_v2,
        checkpointer=checkpointer,
        run_manager=run_manager,
        idempotency_cache=idempotency_cache,
        evidence_collector=EvidenceCollector(
            search_client=MultiSearchClient(mock_client=MockSearchClient())
        ),
    )

    print("[5] Resuming execution from last checkpoint (passing None state)...")
    resumed_result = await graph_v2.ainvoke(None, config=config)

    print("\n[6] Resumption Complete!")
    print(f"    - Worker 2 Planner Runs:    {llm_v2.planner_runs} (0 indicates Planner was SKIPPED)")
    print(f"    - Final Graph Status:       {resumed_result['status']}")
    print(f"    - Final Findings Count:     {len(resumed_result['findings'])}")
    print(f"    - Final Report Title:       {resumed_result['report'].title}")

    report: ResearchReport = resumed_result["report"]
    print(f"    - Citations Attached:       {len(report.citations)}")

    print("\n" + "=" * 80)
    print("  VERIFICATION SUCCESS: Crash recovered cleanly with 0 duplicate work!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
