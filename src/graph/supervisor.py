"""Supervisor Routing Engine.

Controls conditional edge routing across the multi-agent graph, enforcing:
- Single-pass revision cap (maximum 1 review bounce per sub-question).
- Hard budget and timeout circuit breaking.
- Clear hand-offs across specialists.
"""

from typing import Any, Literal

from langgraph.graph import END
from langgraph.types import Send

from src.core.logger import logger
from src.graph.budgets import evaluate_budget
from src.graph.state import ResearchState

SupervisorDecision = Literal[
    "researcher",
    "reviewer",
    "consolidator",
    "writer",
    "emergency_writer",
    "failed",
    "__end__",
]


def _unwrap_lc(d: Any) -> Any:
    if isinstance(d, dict):
        if d.get("lc") == 2 and "kwargs" in d:
            return _unwrap_lc(d["kwargs"])
        return {k: _unwrap_lc(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_unwrap_lc(x) for x in d]
    return d


def _normalize_plan(raw_plan: Any) -> Any:
    if not raw_plan:
        return None
    if isinstance(raw_plan, dict):
        from src.schemas.plan import ResearchPlan

        return ResearchPlan.model_validate(_unwrap_lc(raw_plan))
    return raw_plan


def route_after_planner(state: ResearchState) -> list[Send] | str:
    """Determine the next step after the planner node completes.

    Spawns concurrent parallel researcher workers using LangGraph's Send API,
    one worker task per decomposed sub-question.
    """
    plan = _normalize_plan(state.get("plan"))
    if not plan or not plan.sub_questions:
        logger.error("Planner failed to produce valid sub-questions; routing to failed")
        return "failed"

    run_id = state.get("run_id", "")
    query = state.get("query", "")

    max_subqs = state.get("max_sub_questions")
    sub_questions = plan.sub_questions
    if max_subqs and max_subqs > 0:
        sub_questions = sub_questions[:max_subqs]

    start_time = state.get("start_time", 0.0)
    max_wall_clock = state.get("max_wall_clock_seconds")
    deep_scrape_pref = state.get("deep_scrape", True)

    logger.info(
        "Supervisor fanning out parallel researchers via Send API",
        total_sub_questions=len(sub_questions),
        run_id=run_id,
        max_sub_questions=max_subqs,
        max_wall_clock_seconds=max_wall_clock,
    )
    return [
        Send(
            "researcher",
            {
                "sub_question": sq,
                "index": idx,
                "run_id": run_id,
                "query": query,
                "start_time": start_time,
                "max_wall_clock_seconds": max_wall_clock,
                "deep_scrape": deep_scrape_pref,
            },
        )
        for idx, sq in enumerate(sub_questions)
    ]


def route_after_consolidator(state: ResearchState) -> str:
    """Evaluate budget and findings after all parallel workers join.

    Routes to emergency writer if token or time budgets were exceeded during
    parallel research passes, otherwise advances to the writer node.
    """
    budget = evaluate_budget(state)
    is_resource_breached = budget.is_exceeded and budget.exceeded_metric in ("tokens", "wall_clock")
    if is_resource_breached or state.get("status") == "budget_exceeded":
        logger.warning(
            "Hard budget exceeded in supervisor; routing to emergency writer",
            reason=budget.reason if budget.is_exceeded else "Budget limit breached",
        )
        return "emergency_writer"

    findings = state.get("findings", [])
    if not findings and not state.get("plan"):
        logger.error("No findings gathered and no valid plan; routing to failed")
        return "failed"

    logger.info("Supervisor routing to writer for final report synthesis")
    return "writer"


def route_after_researcher(state: ResearchState) -> str:
    """Determine the next step after a researcher pass completes."""
    logger.debug("Supervisor routing researcher pass to reviewer")
    return "reviewer"


def route_after_reviewer(state: ResearchState) -> str:
    """Determine the next step after the reviewer evaluates researcher findings.

    STRICT CONSTRAINTS ENFORCED HERE:
    1. Hard budget check: if tokens or time limits are breached, route to emergency_writer.
    2. Sub-question cap reached: normal completion, route to writer.
    3. Single-pass revision gate: reviewer can send work back AT MOST ONCE.
    """
    # 1. Evaluate hard budget
    budget = evaluate_budget(state)
    if budget.is_exceeded:
        if budget.exceeded_metric in ("tokens", "wall_clock"):
            logger.warning(
                "Hard budget exceeded in supervisor; routing to emergency writer",
                reason=budget.reason,
            )
            return "emergency_writer"
        logger.info("Supervisor reached sub-question cap; routing to writer")
        return "writer"

    plan = _normalize_plan(state.get("plan"))
    if not plan:
        return "failed"

    current_idx = state.get("current_sub_question_index", 0)
    revision_count = state.get("revision_count", 0)
    review_notes = state.get("review_feedback")

    # If reviewer requested revision AND we haven't reached the 1-revision cap:
    if review_notes and revision_count < 1:
        logger.info(
            "Supervisor routing back to researcher for single permitted revision",
            sub_question_index=current_idx,
            revision_count=revision_count + 1,
            feedback=review_notes,
        )
        return "researcher"

    # All sub-questions completed (or single-question plan completed without active revision)
    if current_idx >= len(plan.sub_questions) or (
        len(plan.sub_questions) == 1 and (review_notes is None or revision_count >= 1)
    ):
        logger.info("Supervisor routing to writer for final report synthesis")
        return "writer"

    # Otherwise, advance to next sub-question
    logger.info(
        "Supervisor advancing to next sub-question",
        next_sub_question_index=current_idx,
        total_sub_questions=len(plan.sub_questions),
    )
    return "researcher"


def route_after_writer(state: ResearchState) -> str:
    """Terminal edge routing once the report writer finishes."""
    return END
