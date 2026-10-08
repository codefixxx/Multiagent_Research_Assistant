"""Chaos tests for crash recovery, checkpoint resumption, and node idempotency in Redis."""

from typing import Any

import pytest
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
from src.tools.evidence_collector import EvidenceCollector
from src.tools.search import MockSearchClient, MultiSearchClient
from tests.conftest import MockChatModel


class CrashTriggerError(RuntimeError):
    """Exception simulating an unexpected worker termination or process crash."""


class ControlledCrashModel(MockChatModel):
    """Mock model that counts specialist invocations and can trigger a crash on demand."""

    should_crash: bool = False
    planner_calls: int = 0
    researcher_calls: int = 0

    def with_structured_output(self, schema: Any, *, include_raw: bool = False, **kwargs: Any):
        base_runnable = super().with_structured_output(schema, include_raw=include_raw, **kwargs)

        async def _intercept(messages: Any) -> Any:
            if schema == ResearchPlan:
                self.planner_calls += 1
                return await base_runnable.ainvoke(messages)
            if schema == ResearcherOutput:
                self.researcher_calls += 1
                if self.should_crash and self.researcher_calls == 2:
                    raise CrashTriggerError("WORKER CRASH: Process terminated midway through sub-question 2!")
                return await base_runnable.ainvoke(messages)
            return await base_runnable.ainvoke(messages)

        return RunnableLambda(_intercept)


@pytest.mark.asyncio
async def test_crash_resumption_from_redis_checkpoint():
    """Simulate worker crash midway through research and assert resumption from last checkpoint."""
    redis_client = await get_redis_client(force_fake=True)
    checkpointer = AsyncShallowRedisSaver(redis_client=redis_client)
    run_manager = RedisRunManager(redis_client=redis_client)
    idempotency_cache = NodeIdempotencyCache(redis_client=redis_client)

    run_id = "chaos-crash-recovery-run-42"
    config: RunnableConfig = {"configurable": {"thread_id": run_id}}

    # Predefined 2-question plan
    two_step_plan = ResearchPlan(
        query="Compare Redis and Memcached memory",
        objective="Analyze memory architectures and caching trade-offs.",
        sub_questions=[
            SubQuestion(
                id="sq_1",
                question="What is Redis memory architecture?",
                rationale="Analyze Redis in-memory storage.",
                search_queries=["Redis memory architecture"],
                status=SubQuestionStatus.PENDING,
            ),
            SubQuestion(
                id="sq_2",
                question="What is Memcached memory architecture?",
                rationale="Analyze Memcached slab allocation.",
                search_queries=["Memcached slab allocation"],
                status=SubQuestionStatus.PENDING,
            ),
        ],
    )

    # =========================================================================
    # Phase 1: Trigger run with simulated crash enabled
    # =========================================================================
    crashing_llm = ControlledCrashModel(fixed_plan=two_step_plan)
    crashing_llm.should_crash = True

    graph_v1 = compile_research_graph(
        llm=crashing_llm,
        checkpointer=checkpointer,
        run_manager=run_manager,
        idempotency_cache=idempotency_cache,
        evidence_collector=EvidenceCollector(
            search_client=MultiSearchClient(mock_client=MockSearchClient())
        ),
    )

    initial_state = create_initial_state(query="Compare Redis and Memcached memory", run_id=run_id)
    await run_manager.init_run(run_id, "Compare Redis and Memcached memory")

    with pytest.raises(CrashTriggerError):
        await graph_v1.ainvoke(initial_state, config=config)

    # Verify execution state after crash
    assert crashing_llm.planner_calls == 1, "Planner should have run once before crash"
    assert crashing_llm.researcher_calls == 2, "Researcher started step 2 and crashed"

    # Inspect checkpoint persisted in Redis
    saved_state = await graph_v1.aget_state(config)
    assert saved_state is not None
    assert saved_state.values.get("plan") is not None
    assert len(saved_state.values.get("findings", [])) >= 1, "Findings from step 1 must be safely persisted"
    # The next node to execute should be researcher
    assert "researcher" in saved_state.next

    # =========================================================================
    # Phase 2: Instantiate NEW runner / worker and RESUME from same thread_id
    # =========================================================================
    healed_llm = ControlledCrashModel(fixed_plan=two_step_plan)
    healed_llm.should_crash = False

    graph_v2 = compile_research_graph(
        llm=healed_llm,
        checkpointer=checkpointer,
        run_manager=run_manager,
        idempotency_cache=idempotency_cache,
        evidence_collector=EvidenceCollector(
            search_client=MultiSearchClient(mock_client=MockSearchClient())
        ),
    )

    # Resume graph execution passing None as input state
    resumed_result = await graph_v2.ainvoke(None, config=config)

    # Assertions on post-resumption behavior:
    # 1. Planner was NOT re-executed in the new worker!
    assert healed_llm.planner_calls == 0, "Planner must NOT re-execute upon resumption from checkpoint"

    # 2. Resumed run completed successfully
    assert resumed_result["status"] == "completed"
    assert isinstance(resumed_result["report"], ResearchReport)

    # 3. Check Redis run manager reflects completion
    meta = await run_manager.get_run_metadata(run_id)
    assert meta is not None
    assert meta["status"] == "completed"
    assert meta["current_node"] == "writer"


@pytest.mark.asyncio
async def test_node_idempotency_avoids_recomputation():
    """Verify idempotency cache returns existing findings and avoids re-executing searches."""
    client = await get_redis_client(force_fake=True)
    cache = NodeIdempotencyCache(redis_client=client)

    run_id = "idempotency-test-run"
    payload = {"sub_question_id": "sq-1", "question": "Explain Raft consensus", "feedback": None}
    cached_data = {
        "findings": [
            {
                "claim": "Raft uses term numbers and leader heartbeats.",
                "source_url": "https://raft.github.io",
                "raw_snippet": "Raft leader election details.",
                "retrieved_at": "2026-10-08T12:00:00Z",
                "status": "success",
            }
        ],
        "is_answered": True,
    }

    # Seed the cache
    await cache.set(run_id, "researcher", payload, cached_data)

    # Query the cache
    hit = await cache.get(run_id, "researcher", payload)
    assert hit is not None
    assert hit["findings"][0]["claim"] == "Raft uses term numbers and leader heartbeats."
    assert hit["is_answered"] is True
