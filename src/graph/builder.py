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
from src.core.logger import logger
from src.core.telemetry import TokenUsage
from src.graph.state import ResearchState
from src.graph.supervisor import (
    route_after_planner,
    route_after_reviewer,
)
from src.schemas.report import Citation, ReportSection, ResearchReport
from src.schemas.trace import StepTrace


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


def build_research_graph(llm: BaseChatModel | None = None) -> StateGraph:
    """Build and return an uncompiled StateGraph for the research system."""

    async def planner_node(state: ResearchState) -> dict[str, Any]:
        step = state.get("step_count", 0) + 1
        query = state.get("query", "")
        logger.info("Executing Planner node", step=step, query=query)

        plan, tokens, latency = await plan_research(query=query, llm=llm)

        cum_tokens = state.get("total_tokens", TokenUsage())
        cum_tokens.add(tokens.prompt_tokens, tokens.completion_tokens, tokens.estimated_cost_usd)

        trace = create_step_trace(
            step_number=step,
            agent_name="planner",
            input_data={"query": query},
            output_data={"sub_questions_count": len(plan.sub_questions)},
            tokens=tokens,
            latency_ms=latency,
        )

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
        plan = state.get("plan")
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

        # Context evidence incorporating any feedback from reviewer
        evidence = (
            f"Sub-question target: {sub_question.question}\n"
            f"Rationale: {sub_question.rationale}\n"
            f"Search Queries: {', '.join(sub_question.search_queries)}\n"
        )
        if feedback:
            evidence += f"\nReviewer Revision Guidance: {feedback}\n"

        output, tokens, latency = await research_subquestion(
            sub_question=sub_question,
            evidence_context=evidence,
            llm=llm,
        )

        cum_tokens = state.get("total_tokens", TokenUsage())
        cum_tokens.add(tokens.prompt_tokens, tokens.completion_tokens, tokens.estimated_cost_usd)

        trace = create_step_trace(
            step_number=step,
            agent_name="researcher",
            input_data={"sub_question_id": sub_question.id, "has_feedback": bool(feedback)},
            output_data={"findings_count": len(output.findings), "is_answered": output.is_answered},
            tokens=tokens,
            latency_ms=latency,
        )

        return {
            "current_sub_question_findings": output.findings,
            "findings": state.get("findings", []) + output.findings,
            "status": "reviewing",
            "step_count": step,
            "total_tokens": cum_tokens,
            "audit_traces": state.get("audit_traces", []) + [trace],
        }

    async def reviewer_node(state: ResearchState) -> dict[str, Any]:
        step = state.get("step_count", 0) + 1
        plan = state.get("plan")
        if not plan:
            return {"status": "failed", "error_message": "Missing research plan in reviewer node"}

        idx = state.get("current_sub_question_index", 0)
        sub_question = plan.sub_questions[idx]
        findings = state.get("current_sub_question_findings", [])
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

        cum_tokens = state.get("total_tokens", TokenUsage())
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
        findings = state.get("findings", [])
        logger.info("Executing Writer node", step=step, findings_count=len(findings))

        report, tokens, latency = await write_report(
            query=query,
            findings=findings,
            llm=llm,
        )

        cum_tokens = state.get("total_tokens", TokenUsage())
        cum_tokens.add(tokens.prompt_tokens, tokens.completion_tokens, tokens.estimated_cost_usd)

        trace = create_step_trace(
            step_number=step,
            agent_name="writer",
            input_data={"query": query, "findings_count": len(findings)},
            output_data={"title": report.title, "sections_count": len(report.sections)},
            tokens=tokens,
            latency_ms=latency,
        )

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
        findings = state.get("findings", [])
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


def compile_research_graph(llm: BaseChatModel | None = None, checkpointer: Any = None):
    """Build and compile the research graph ready for execution."""
    builder = build_research_graph(llm=llm)
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
