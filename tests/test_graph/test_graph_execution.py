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
    from tests.conftest import MockChatModel
    from src.schemas.finding import ResearcherOutput, FindingRecord, ExtractionStatus

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
