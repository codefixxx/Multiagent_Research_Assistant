"""Integration tests for the LangGraph multi-agent state machine."""

import pytest

from src.core.telemetry import TokenUsage
from src.graph.builder import compile_research_graph, create_initial_state
from src.schemas.report import ResearchReport


@pytest.mark.asyncio
async def test_full_graph_execution_happy_path(mock_llm):
    """Complete graph execution from query to cited report using mock model."""
    graph = compile_research_graph(llm=mock_llm)
    initial_state = create_initial_state(query="Compare Redis vs Memcached latency")

    final_state = await graph.ainvoke(initial_state)

    assert final_state["status"] == "completed"
    assert isinstance(final_state["report"], ResearchReport)
    assert len(final_state["report"].title) > 0
    assert len(final_state["report"].sections) >= 1
    assert len(final_state["report"].citations) >= 1

    # Verify audit traces recorded every node transition
    traces = final_state["audit_traces"]
    agent_names = [t.agent_name for t in traces]
    assert "planner" in agent_names
    assert "researcher" in agent_names
    assert "reviewer" in agent_names
    assert "writer" in agent_names

    # Verify cumulative token tracking
    assert final_state["total_tokens"].total_tokens > 0


@pytest.mark.asyncio
async def test_graph_emergency_writer_on_budget_exceeded(mock_llm):
    """Graph must break execution and route to emergency writer if budget limit is breached."""
    graph = compile_research_graph(llm=mock_llm)
    initial_state = create_initial_state(query="Compare Redis vs Memcached latency")

    # Pre-breach token budget to simulate runaway spend
    initial_state["total_tokens"] = TokenUsage(total_tokens=160000)

    final_state = await graph.ainvoke(initial_state)

    assert final_state["status"] == "budget_exceeded"
    assert "budget" in final_state["report"].title.lower()
    assert "emergency_writer" in [t.agent_name for t in final_state["audit_traces"]]


@pytest.mark.asyncio
async def test_parallel_fan_out_multi_worker_execution(mock_llm):
    """Verify that multiple sub-questions fan out concurrently and reduce cleanly into state."""
    graph = compile_research_graph(llm=mock_llm)
    initial_state = create_initial_state(
        query="Investigate distributed consensus in Raft, Paxos, and Zab"
    )

    final_state = await graph.ainvoke(initial_state)

    assert final_state["status"] == "completed"
    assert len(final_state["findings"]) >= 2
    # Verify traces captured planner, parallel researchers, reviewers, and writer
    agent_names = [t.agent_name for t in final_state["audit_traces"]]
    assert agent_names.count("planner") == 1
    assert agent_names.count("researcher") >= 2
    assert agent_names.count("reviewer") >= 2
    assert agent_names.count("writer") == 1
    # Check that final report references multiple findings
    assert len(final_state["report"].sections) >= 1
    assert final_state["total_tokens"].total_tokens > 0


@pytest.mark.asyncio
async def test_deep_research_gap_filler_executes_on_unanswered_subquestions():
    """Verify that when parallel workers leave a gap, the gap_filler node triggers and completes."""
    from langchain_core.runnables import RunnableLambda

    from src.schemas.finding import ExtractionStatus, FindingRecord, ResearcherOutput
    from tests.conftest import MockChatModel

    class GapInducingMockModel(MockChatModel):
        def with_structured_output(self, schema, *, include_raw=False, **kwargs):
            if schema == ResearcherOutput:

                def _invoke(messages):
                    msg_str = str(messages)
                    if "overview documentation" in msg_str:
                        # Gap filler recovers findings!
                        res = ResearcherOutput(
                            sub_question_id="sq_1",
                            is_answered=True,
                            findings=[
                                FindingRecord(
                                    id="find_recovered",
                                    sub_question_id="sq_1",
                                    claim="Recovered evidence during deep gap fill.",
                                    source_url="https://example.com/gap-recovery",
                                    snippet="Evidence recovered successfully.",
                                )
                            ],
                            summary="Recovered evidence during gap fill.",
                            status=ExtractionStatus.SUCCESS,
                        )
                    else:
                        # Initial pass has no findings (simulates a knowledge gap)
                        res = ResearcherOutput(
                            sub_question_id="sq_1",
                            is_answered=False,
                            findings=[],
                            summary="No initial evidence found.",
                            status=ExtractionStatus.NO_RESULTS,
                        )
                    if include_raw:
                        return {"raw": None, "parsed": res, "parsing_error": None}
                    return res

                return RunnableLambda(_invoke)
            return super().with_structured_output(schema, include_raw=include_raw, **kwargs)

    graph = compile_research_graph(llm=GapInducingMockModel())
    initial_state = create_initial_state(query="Compare Kafka vs RabbitMQ")

    final_state = await graph.ainvoke(initial_state)

    assert final_state["status"] == "completed"
    assert final_state["gap_fill_attempts"] == 1
    agent_names = [t.agent_name for t in final_state["audit_traces"]]
    assert "gap_filler" in agent_names
    assert len(final_state["findings"]) >= 1
    assert any(f.id == "find_recovered" for f in final_state["findings"])


@pytest.mark.asyncio
async def test_graph_human_in_the_loop_steering(mock_llm):
    """Verify Human-in-the-Loop plan gate: pauses execution, accepts modified plan, and proceeds."""
    import asyncio

    from src.api.job_runner import job_service
    from src.schemas.plan import ResearchPlan, SubQuestion

    await job_service.initialize(force_new=True)
    run_id = "test-graph-hitl-01"

    assert job_service.run_manager is not None
    await job_service.run_manager.init_run(
        run_id=run_id,
        query="Vector database architectural tradeoffs",
        hitl_enabled=True,
    )

    graph = compile_research_graph(llm=mock_llm, run_manager=job_service.run_manager)
    initial_state = create_initial_state(
        query="Vector database architectural tradeoffs",
        run_id=run_id,
        hitl_enabled=True,
    )

    # Launch graph in background task
    task = asyncio.create_task(graph.ainvoke(initial_state))

    # Wait until planner node has saved the plan and paused at plan_gate
    for _ in range(30):
        plan_in_db = await job_service.run_manager.get_plan(run_id)
        if plan_in_db is not None:
            break
        await asyncio.sleep(0.1)

    # Steer plan with customized sub-question
    custom_plan = ResearchPlan(
        query="Vector database architectural tradeoffs",
        objective="Analyze disk-backed indexing vs RAM memory usage",
        sub_questions=[
            SubQuestion(
                id="sq_steered_1",
                question="What is the RAM overhead of HNSW graphs?",
                rationale="Evaluate memory scaling bottlenecks",
                search_queries=["HNSW memory footprint per 1M vectors"],
            )
        ],
    )

    # Submit human decision to resume graph
    await job_service.submit_plan_decision(
        run_id=run_id,
        action="modify",
        modified_plan=custom_plan,
    )

    final_state = await task

    assert final_state["status"] == "completed"
    assert final_state["plan_approved"] is True
    # The final plan in state matches the steered plan
    assert len(final_state["plan"].sub_questions) == 1
    assert final_state["plan"].sub_questions[0].id == "sq_steered_1"
    assert "HNSW" in final_state["plan"].sub_questions[0].question
