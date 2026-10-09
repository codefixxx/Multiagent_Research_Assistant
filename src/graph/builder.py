"""LangGraph multi-agent research graph construction.

Assembles Planner, Researcher, Reviewer, Writer, and Emergency Writer into
a governed state machine with supervisor conditional edges and hard budgets.
"""

import time
import uuid
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from src.agents.planner import plan_research
from src.agents.researcher import research_subquestion
from src.agents.reviewer import evaluate_research
from src.agents.writer import write_report
from src.config import settings
from src.core.logger import logger
from src.core.telemetry import TokenUsage
from src.graph.state import ResearchState
from src.graph.supervisor import (
    route_after_planner,
    route_after_reviewer,
)
from src.schemas.finding import FindingRecord
from src.schemas.report import Citation, ReportSection, ResearchReport
from src.schemas.trace import StepTrace
from src.tools.evidence_collector import EvidenceCollector


def create_step_trace(
    step_number: int,
    agent_name: str,
    input_data: dict[str, Any],
    output_data: dict[str, Any],
    tokens: TokenUsage,
    latency_ms: float,
) -> StepTrace:
    """Helper to assemble a typed audit trace record."""
    return StepTrace(
        step_number=step_number,
        agent_name=agent_name,
        input_data=input_data,
        output_data=output_data,
        token_usage=tokens,
        latency_ms=latency_ms,
        status="success",
    )


def _unwrap_lc(d: Any) -> Any:
    if isinstance(d, dict):
        if d.get("lc") == 2 and "kwargs" in d:
            return _unwrap_lc(d["kwargs"])
        return {k: _unwrap_lc(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_unwrap_lc(x) for x in d]
    return d


def _normalize_tokens(raw_tokens: Any) -> TokenUsage:
    if isinstance(raw_tokens, dict):
        unwrapped = _unwrap_lc(raw_tokens)
        return TokenUsage(**unwrapped)
    if isinstance(raw_tokens, TokenUsage):
        return raw_tokens
    return TokenUsage()


def _normalize_plan(raw_plan: Any) -> Any:
    if not raw_plan:
        return None
    if isinstance(raw_plan, dict):
        from src.schemas.plan import ResearchPlan

        return ResearchPlan.model_validate(_unwrap_lc(raw_plan))
    return raw_plan


def _normalize_findings(raw_findings: Any) -> list[FindingRecord]:
    if not raw_findings:
        return []
    res = []
    for f in raw_findings:
        if isinstance(f, dict):
            res.append(FindingRecord.model_validate(_unwrap_lc(f)))
        elif isinstance(f, FindingRecord):
            res.append(f)
    return res


def build_research_graph(
    llm: BaseChatModel | None = None,
    evidence_collector: EvidenceCollector | None = None,
    run_manager: Any = None,
    idempotency_cache: Any = None,
) -> StateGraph:
    """Build and return an uncompiled StateGraph for the research system."""

    async def planner_node(state: ResearchState) -> dict[str, Any]:
        step = state.get("step_count", 0) + 1
        query = state.get("query", "")
        run_id = state.get("run_id", "")
        logger.info("Executing Planner node", step=step, query=query)

        plan, tokens, latency = await plan_research(query=query, llm=llm)

        cum_tokens = _normalize_tokens(state.get("total_tokens"))
        cum_tokens.add(tokens.prompt_tokens, tokens.completion_tokens, tokens.estimated_cost_usd)

        trace = create_step_trace(
            step_number=step,
            agent_name="planner",
            input_data={"query": query},
            output_data={"sub_questions_count": len(plan.sub_questions)},
            tokens=tokens,
            latency_ms=latency,
        )

        if run_manager and run_id:
            try:
                await run_manager.update_run_status(
                    run_id=run_id,
                    status="researching",
                    current_node="planner",
                    step_count=step,
                    total_tokens=cum_tokens.total_tokens,
                )
                await run_manager.record_completed_step(
                    run_id=run_id,
                    node_name="planner",
                    step_number=step,
                )
            except Exception as e:
                logger.debug("Failed updating run_manager in planner", error=str(e))

        return {
            "plan": plan,
            "current_sub_question_index": 0,
            "revision_count": 0,
            "status": "researching",
            "step_count": step,
            "total_tokens": cum_tokens,
            "audit_traces": state.get("audit_traces", []) + [trace],
        }

    async def researcher_node(state: ResearchState) -> dict[str, Any]:
        step = state.get("step_count", 0) + 1
        plan = _normalize_plan(state.get("plan"))
        if not plan:
            return {"status": "failed", "error_message": "Missing research plan in researcher node"}

        idx = state.get("current_sub_question_index", 0)
        sub_question = plan.sub_questions[idx]
        feedback = state.get("review_feedback")

        logger.info(
            "Executing Researcher node",
            step=step,
            sub_question_id=sub_question.id,
            is_revision=bool(feedback),
        )

        run_id = state.get("run_id", "")
        findings: list[FindingRecord] = []
        is_answered: bool = True
        tokens = TokenUsage()
        latency = 0.0

        cache_payload = {
            "sub_question_id": sub_question.id,
            "question": sub_question.question,
            "feedback": feedback,
        }
        cached_result = None
        if idempotency_cache and run_id:
            try:
                cached_result = await idempotency_cache.get(run_id, "researcher", cache_payload)
            except Exception as e:
                logger.debug("Idempotency cache lookup failed", error=str(e))

        if cached_result and "findings" in cached_result:
            logger.info("Researcher idempotency cache hit", sub_question_id=sub_question.id)
            findings = [FindingRecord.model_validate(f) for f in cached_result["findings"]]
            is_answered = cached_result.get("is_answered", True)
        else:
            collector = evidence_collector
            is_mock_llm = "mock" in type(llm).__name__.lower()
            if collector is None:
                if (
                    is_mock_llm
                    or settings.LLM_PROVIDER == "mock"
                    or settings.SEARCH_ENGINE == "mock"
                ):
                    from src.tools.search import MockSearchClient, MultiSearchClient

                    collector = EvidenceCollector(
                        search_client=MultiSearchClient(mock_client=MockSearchClient())
                    )
                else:
                    collector = EvidenceCollector()

            queries = (
                list(sub_question.search_queries)
                if sub_question.search_queries
                else [sub_question.question]
            )
            if feedback:
                queries.append(f"{sub_question.question} {feedback[:60]}")

            evidence_res = await collector.collect_evidence_for_queries(
                queries=queries,
                deep_scrape=not is_mock_llm,
            )
            evidence = evidence_res.formatted_context
            if feedback:
                evidence += f"\n\nReviewer Revision Guidance: {feedback}\n"

            output, tokens, latency = await research_subquestion(
                sub_question=sub_question,
                evidence_context=evidence,
                llm=llm,
            )
            findings = output.findings
            is_answered = output.is_answered

            if idempotency_cache and run_id:
                try:
                    await idempotency_cache.set(
                        run_id=run_id,
                        node_name="researcher",
                        payload=cache_payload,
                        output_data={
                            "findings": [f.model_dump() for f in findings],
                            "is_answered": is_answered,
                        },
                    )
                except Exception as e:
                    logger.debug("Idempotency cache write failed", error=str(e))

        cum_tokens = _normalize_tokens(state.get("total_tokens"))
        cum_tokens.add(tokens.prompt_tokens, tokens.completion_tokens, tokens.estimated_cost_usd)

        trace = create_step_trace(
            step_number=step,
            agent_name="researcher",
            input_data={"sub_question_id": sub_question.id, "has_feedback": bool(feedback)},
            output_data={"findings_count": len(findings), "is_answered": is_answered},
            tokens=tokens,
            latency_ms=latency,
        )

        if run_manager and run_id:
            try:
                await run_manager.update_run_status(
                    run_id=run_id,
                    status="reviewing",
                    current_node="researcher",
                    step_count=step,
                    total_tokens=cum_tokens.total_tokens,
                )
                await run_manager.record_completed_step(
                    run_id=run_id,
                    node_name="researcher",
                    step_number=step,
                )
            except Exception as e:
                logger.debug("Failed updating run_manager in researcher", error=str(e))

        existing_findings = _normalize_findings(state.get("findings", []))
        return {
            "current_sub_question_findings": findings,
            "findings": existing_findings + findings,
            "status": "reviewing",
            "step_count": step,
            "total_tokens": cum_tokens,
            "audit_traces": state.get("audit_traces", []) + [trace],
        }

    async def reviewer_node(state: ResearchState) -> dict[str, Any]:
        step = state.get("step_count", 0) + 1
        plan = _normalize_plan(state.get("plan"))
        if not plan:
            return {"status": "failed", "error_message": "Missing research plan in reviewer node"}

        idx = state.get("current_sub_question_index", 0)
        sub_question = plan.sub_questions[idx]
        findings = _normalize_findings(state.get("current_sub_question_findings", []))
        revision_count = state.get("revision_count", 0)

        logger.info(
            "Executing Reviewer node",
            step=step,
            sub_question_id=sub_question.id,
            current_revision_count=revision_count,
        )

        evaluation, tokens, latency = await evaluate_research(
            sub_question=sub_question,
            findings=findings,
            llm=llm,
        )

        cum_tokens = _normalize_tokens(state.get("total_tokens"))
        cum_tokens.add(tokens.prompt_tokens, tokens.completion_tokens, tokens.estimated_cost_usd)

        trace = create_step_trace(
            step_number=step,
            agent_name="reviewer",
            input_data={"sub_question_id": sub_question.id, "findings_count": len(findings)},
            output_data={
                "is_approved": evaluation.quality_score >= 0.5,
                "score": evaluation.quality_score,
            },
            tokens=tokens,
            latency_ms=latency,
        )

        run_id = state.get("run_id", "")
        if run_manager and run_id:
            try:
                await run_manager.update_run_status(
                    run_id=run_id,
                    status="reviewing",
                    current_node="reviewer",
                    step_count=step,
                    total_tokens=cum_tokens.total_tokens,
                )
                await run_manager.record_completed_step(
                    run_id=run_id,
                    node_name="reviewer",
                    step_number=step,
                )
            except Exception as e:
                logger.debug("Failed updating run_manager in reviewer", error=str(e))

        # Enforce single-pass revision constraint:
        # If not approved AND revision_count < 1 -> send back for exactly 1 revision pass
        if not evaluation.is_approved and revision_count < 1:
            logger.info(
                "Reviewer requested single permitted revision", sub_question_id=sub_question.id
            )
            return {
                "revision_count": revision_count + 1,
                "review_feedback": evaluation.feedback,
                "step_count": step,
                "total_tokens": cum_tokens,
                "audit_traces": state.get("audit_traces", []) + [trace],
            }

        # Otherwise approved or revision cap exhausted: advance sub-question pointer
        logger.info(
            "Reviewer approved sub-question or reached revision cap",
            sub_question_id=sub_question.id,
        )
        return {
            "current_sub_question_index": idx + 1,
            "revision_count": 0,
            "review_feedback": None,
            "step_count": step,
            "total_tokens": cum_tokens,
            "audit_traces": state.get("audit_traces", []) + [trace],
        }

    async def writer_node(state: ResearchState) -> dict[str, Any]:
        step = state.get("step_count", 0) + 1
        query = state.get("query", "")
        findings = _normalize_findings(state.get("findings", []))
        logger.info("Executing Writer node", step=step, findings_count=len(findings))

        report, tokens, latency = await write_report(
            query=query,
            findings=findings,
            llm=llm,
        )

        cum_tokens = _normalize_tokens(state.get("total_tokens"))
        cum_tokens.add(tokens.prompt_tokens, tokens.completion_tokens, tokens.estimated_cost_usd)

        trace = create_step_trace(
            step_number=step,
            agent_name="writer",
            input_data={"query": query, "findings_count": len(findings)},
            output_data={"title": report.title, "sections_count": len(report.sections)},
            tokens=tokens,
            latency_ms=latency,
        )

        run_id = state.get("run_id", "")
        if run_manager and run_id:
            try:
                await run_manager.update_run_status(
                    run_id=run_id,
                    status="completed",
                    current_node="writer",
                    step_count=step,
                    total_tokens=cum_tokens.total_tokens,
                )
                await run_manager.record_completed_step(
                    run_id=run_id,
                    node_name="writer",
                    step_number=step,
                )
            except Exception as e:
                logger.debug("Failed updating run_manager in writer", error=str(e))

        return {
            "report": report,
            "status": "completed",
            "step_count": step,
            "total_tokens": cum_tokens,
            "audit_traces": state.get("audit_traces", []) + [trace],
        }

    async def emergency_writer_node(state: ResearchState) -> dict[str, Any]:
        step = state.get("step_count", 0) + 1
        query = state.get("query", "")
        findings = _normalize_findings(state.get("findings", []))
        logger.warning("Executing Emergency Writer node (budget ceiling breached)", step=step)

        # Assemble best-effort emergency report
        emergency_report = ResearchReport(
            title=f"Research Report (Budget Ceilings Reached): {query[:60]}",
            executive_summary=(
                "NOTICE: This report was assembled under emergency hard-budget constraints. "
                "One or more operational ceilings (token budget or wall-clock timeout) were exceeded. "
                "The findings presented below represent all verified evidence collected prior to termination."
            ),
            sections=[
                ReportSection(
                    title="Interim Findings",
                    content=(
                        f"Collected {len(findings)} verified finding records before budget limits triggered. "
                        + (
                            " ".join([f"- {f.claim}" for f in findings[:5]])
                            if findings
                            else "No findings gathered."
                        )
                    ),
                    citation_ids=[],
                )
            ],
            citations=[
                Citation(citation_id=f"[cite_{i}]", source_url=f.source_url, verified_claim=f.claim)
                for i, f in enumerate(findings, 1)
            ],
        )
        emergency_report.compile_markdown()

        trace = create_step_trace(
            step_number=step,
            agent_name="emergency_writer",
            input_data={"findings_count": len(findings)},
            output_data={"status": "budget_exceeded"},
            tokens=TokenUsage(),
            latency_ms=1.0,
        )

        return {
            "report": emergency_report,
            "status": "budget_exceeded",
            "step_count": step,
            "audit_traces": state.get("audit_traces", []) + [trace],
        }

    builder = StateGraph(ResearchState)  # type: ignore[arg-type]

    # Register nodes
    builder.add_node("planner", planner_node)
    builder.add_node("researcher", researcher_node)
    builder.add_node("reviewer", reviewer_node)
    builder.add_node("writer", writer_node)
    builder.add_node("emergency_writer", emergency_writer_node)

    # Connect edges
    builder.add_edge(START, "planner")
    builder.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "researcher": "researcher",
            "failed": END,
        },
    )
    builder.add_edge("researcher", "reviewer")
    builder.add_conditional_edges(
        "reviewer",
        route_after_reviewer,
        {
            "researcher": "researcher",
            "writer": "writer",
            "emergency_writer": "emergency_writer",
            "failed": END,
        },
    )
    builder.add_edge("writer", END)
    builder.add_edge("emergency_writer", END)

    return builder


def compile_research_graph(
    llm: BaseChatModel | None = None,
    checkpointer: Any = None,
    evidence_collector: EvidenceCollector | None = None,
    run_manager: Any = None,
    idempotency_cache: Any = None,
):
    """Build and compile the research graph ready for execution."""
    builder = build_research_graph(
        llm=llm,
        evidence_collector=evidence_collector,
        run_manager=run_manager,
        idempotency_cache=idempotency_cache,
    )
    return builder.compile(checkpointer=checkpointer)


def create_initial_state(query: str, run_id: str | None = None) -> ResearchState:
    """Initialize a clean, typed ResearchState instance for a new run."""
    return ResearchState(
        run_id=run_id or str(uuid.uuid4()),
        query=query,
        plan=None,
        current_sub_question_index=0,
        findings=[],
        current_sub_question_findings=[],
        revision_count=0,
        review_feedback=None,
        report=None,
        status="planning",
        total_tokens=TokenUsage(),
        start_time=time.time(),
        step_count=0,
        audit_traces=[],
        error_message=None,
    )
