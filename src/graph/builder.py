"""LangGraph multi-agent research graph construction.

Assembles Planner, Researcher, Reviewer, Writer, and Emergency Writer into
a governed state machine with supervisor conditional edges and hard budgets.
"""

import re
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
from src.core.exceptions import classify_error
from src.core.logger import logger
from src.core.telemetry import TokenUsage, calculate_token_cost
from src.core.tracer import async_trace_span
from src.graph.budgets import can_attempt_gap_fill, evaluate_budget
from src.graph.state import ResearchState
from src.graph.supervisor import (
    route_after_consolidator,
    route_after_plan_gate,
    route_after_planner,
)
from src.schemas.finding import FindingRecord
from src.schemas.plan import SubQuestion
from src.schemas.report import Citation, ReportSection, ResearchReport
from src.schemas.trace import StepTrace, ToolCallRecord
from src.tools.evidence_collector import EvidenceCollector


def create_step_trace(
    step_number: int,
    agent_name: str,
    input_data: dict[str, Any],
    output_data: dict[str, Any],
    tokens: TokenUsage,
    latency_ms: float,
    tool_calls: list[ToolCallRecord] | None = None,
) -> StepTrace:
    """Helper to assemble a typed audit trace record."""
    return StepTrace(
        step_number=step_number,
        agent_name=agent_name,
        input_data=input_data,
        output_data=output_data,
        tool_calls=tool_calls or [],
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
    llm_planner: BaseChatModel | None = None,
    llm_researcher: BaseChatModel | None = None,
    llm_reviewer: BaseChatModel | None = None,
    llm_writer: BaseChatModel | None = None,
    evidence_collector: EvidenceCollector | None = None,
    run_manager: Any = None,
    idempotency_cache: Any = None,
) -> StateGraph:
    """Build and return an uncompiled StateGraph for the research system."""
    active_planner_llm = llm_planner or llm
    active_researcher_llm = llm_researcher or llm
    active_reviewer_llm = llm_reviewer or llm
    active_writer_llm = llm_writer or llm

    async def planner_node(state: ResearchState) -> dict[str, Any]:
        step = 1
        query = state.get("query", "")
        run_id = state.get("run_id", "")
        max_subqs = state.get("max_sub_questions")
        focus_mode = state.get("focus_mode", "general")
        steering_feedback = state.get("steering_feedback")
        logger.info(
            "Executing Planner node",
            step=step,
            query=query,
            max_sub_questions=max_subqs,
            focus_mode=focus_mode,
            has_steering=bool(steering_feedback),
        )

        planner_model = (
            getattr(active_planner_llm, "model_name", None)
            or getattr(active_planner_llm, "model", None)
            or "default"
        )
        try:
            async with async_trace_span(
                name="agent.planner",
                run_id=run_id,
                attributes={
                    "step": step,
                    "agent.role": "planner",
                    "query": query,
                    "llm.model": str(planner_model),
                },
            ) as span_ctx:
                plan, tokens, latency = await plan_research(
                    query=query,
                    llm=active_planner_llm,
                    max_sub_questions=max_subqs,
                    focus_mode=focus_mode,
                    steering_feedback=steering_feedback,
                )
                cost_usd = calculate_token_cost(
                    str(planner_model), tokens.prompt_tokens, tokens.completion_tokens
                )
                tokens.estimated_cost_usd = cost_usd
                span_ctx.update(
                    {
                        "sub_questions_count": len(plan.sub_questions),
                        "tokens.prompt": tokens.prompt_tokens,
                        "tokens.completion": tokens.completion_tokens,
                        "tokens.total": tokens.total_tokens,
                        "cost.usd": cost_usd,
                        "latency_ms": latency,
                    }
                )

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
                    plan_dict = plan.model_dump(mode="json") if hasattr(plan, "model_dump") else plan
                    await run_manager.save_plan(run_id=run_id, plan_data=plan_dict)
                    next_status = "planning" if (state.get("hitl_enabled") and not state.get("plan_approved")) else "researching"
                    await run_manager.update_run_status(
                        run_id=run_id,
                        status=next_status,
                        current_node="planner",
                        step_count=step,
                        total_tokens=tokens.total_tokens,
                    )
                    await run_manager.record_completed_step(
                        run_id=run_id,
                        node_name="planner",
                        step_number=step,
                    )
                except Exception as e:
                    logger.debug("Failed updating run_manager in planner", error=str(e))

            next_status = "planning" if (state.get("hitl_enabled") and not state.get("plan_approved")) else "researching"
            return {
                "plan": plan,
                "current_sub_question_index": 0,
                "revision_count": 0,
                "status": next_status,
                "step_count": 1,
                "total_tokens": tokens,
                "audit_traces": [trace],
            }
        except Exception as exc:
            classified = classify_error(
                exc,
                model_name=str(planner_model) if planner_model else None,
                node="planner",
            )
            logger.error(
                "Planner node execution failed",
                run_id=run_id,
                code=classified.code,
                error=classified.message,
            )
            raise classified from exc

    async def plan_gate_node(state: ResearchState) -> dict[str, Any]:
        run_id = state.get("run_id", "")
        plan = _normalize_plan(state.get("plan"))
        hitl_enabled = state.get("hitl_enabled", False)

        # If HITL review is NOT enabled, or plan was already approved, pass straight through
        if not hitl_enabled or state.get("plan_approved", False):
            return {"plan_approved": True, "status": "researching"}

        logger.info(
            "Plan gate activated: waiting for Human-in-the-Loop review",
            run_id=run_id,
            sub_questions_count=len(plan.sub_questions) if plan else 0,
        )

        plan_dict = plan.model_dump(mode="json") if hasattr(plan, "model_dump") else plan

        if run_manager and run_id:
            try:
                await run_manager.update_run_status(
                    run_id=run_id,
                    status="awaiting_approval",
                    current_node="plan_gate",
                )
                await run_manager.save_plan(run_id, plan_dict)
            except Exception as e:
                logger.debug("Failed updating run_manager in plan_gate", error=str(e))

        from src.api.events import broadcaster
        try:
            await broadcaster.broadcast(
                run_id=run_id,
                event="awaiting_plan_approval",
                data={
                    "status": "awaiting_approval",
                    "plan": plan_dict,
                    "sub_questions": [
                        sq.model_dump(mode="json") if hasattr(sq, "model_dump") else sq
                        for sq in (plan.sub_questions if plan else [])
                    ],
                    "message": "Research plan formulated. Awaiting your approval or steering.",
                },
            )
        except Exception as e:
            logger.debug("Failed broadcasting awaiting_plan_approval", error=str(e))

        from src.api.job_runner import job_service
        decision = await job_service.wait_for_plan_decision(run_id=run_id, timeout=900)
        action = decision.get("action", "approve")

        if action == "modify" and decision.get("modified_plan"):
            mod_plan = _normalize_plan(decision["modified_plan"])
            logger.info("Human steered research plan with custom edits", run_id=run_id)
            if run_manager and run_id:
                try:
                    await run_manager.save_plan(
                        run_id,
                        mod_plan.model_dump(mode="json") if hasattr(mod_plan, "model_dump") else mod_plan,
                    )
                    await run_manager.update_run_status(run_id=run_id, status="researching", current_node="researcher")
                except Exception as e:
                    logger.debug("Failed saving modified plan to run_manager", error=str(e))
            return {
                "plan": mod_plan,
                "plan_approved": True,
                "status": "researching",
                "steering_feedback": None,
            }

        elif action == "regenerate":
            feedback = decision.get("feedback", "")
            logger.info("Human requested plan regeneration with feedback", run_id=run_id, feedback=feedback)
            if run_manager and run_id:
                try:
                    await run_manager.update_run_status(run_id=run_id, status="planning", current_node="planner")
                except Exception as e:
                    logger.debug("Failed updating run status on regeneration", error=str(e))
            return {
                "plan_approved": False,
                "steering_feedback": feedback,
                "status": "planning",
            }

        elif action == "reject":
            logger.warning("Human rejected research plan; cancelling execution", run_id=run_id)
            if run_manager and run_id:
                try:
                    await run_manager.update_run_status(run_id=run_id, status="cancelled", error_message="Plan rejected by user.")
                except Exception as e:
                    logger.debug("Failed updating run status on rejection", error=str(e))
            return {
                "status": "cancelled",
                "error_message": "Plan rejected by user.",
            }

        else: # approve
            logger.info("Human approved research plan as-is", run_id=run_id)
            if run_manager and run_id:
                try:
                    await run_manager.update_run_status(run_id=run_id, status="researching", current_node="researcher")
                except Exception as e:
                    logger.debug("Failed updating run status on approval", error=str(e))
            return {
                "plan_approved": True,
                "status": "researching",
                "steering_feedback": None,
            }

    async def researcher_node(payload: Any) -> dict[str, Any]:
        raw_sq = payload.get("sub_question") if isinstance(payload, dict) else getattr(payload, "sub_question", None)
        if raw_sq:
            if isinstance(raw_sq, dict):
                sub_question = SubQuestion.model_validate(_unwrap_lc(raw_sq))
            else:
                sub_question = raw_sq
            idx = payload.get("index", 0)
            run_id = payload.get("run_id", "")
            deep_scrape_flag = payload.get("deep_scrape", True)
            start_time = payload.get("start_time", 0.0)
            max_wall_clock = payload.get("max_wall_clock_seconds")
            focus_mode = payload.get("focus_mode", "general")
        else:
            plan = _normalize_plan(payload.get("plan"))
            if not plan:
                return {"status": "failed", "error_message": "Missing research plan in worker"}
            idx = payload.get("current_sub_question_index", 0)
            sub_question = plan.sub_questions[idx]
            run_id = payload.get("run_id", "")
            deep_scrape_flag = payload.get("deep_scrape", True)
            start_time = payload.get("start_time", 0.0)
            max_wall_clock = payload.get("max_wall_clock_seconds")
            focus_mode = payload.get("focus_mode", "general")

        step_res = 2 + (idx * 2)
        step_rev = 3 + (idx * 2)

        logger.info(
            "Executing parallel Researcher worker",
            sub_question_id=sub_question.id,
            worker_index=idx,
        )

        worker_tokens = TokenUsage()
        traces: list[StepTrace] = []
        worker_steps = 0

        # 1. Evidence gathering & Researcher pass
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

        # Check idempotency cache
        cache_payload = {
            "sub_question_id": sub_question.id,
            "question": sub_question.question,
        }
        cached_result = None
        if idempotency_cache and run_id:
            try:
                cached_result = await idempotency_cache.get(run_id, "researcher", cache_payload)
            except Exception as e:
                logger.debug("Idempotency cache lookup failed", error=str(e))

        res_model_name = (
            getattr(active_researcher_llm, "model_name", None)
            or getattr(active_researcher_llm, "model", None)
            or "default"
        )
        rev_model_name = (
            getattr(active_reviewer_llm, "model_name", None)
            or getattr(active_reviewer_llm, "model", None)
            or "default"
        )

        tool_records: list[ToolCallRecord] = []
        if cached_result and "findings" in cached_result:
            logger.info("Researcher worker idempotency cache hit", sub_question_id=sub_question.id)
            findings = [FindingRecord.model_validate(f) for f in cached_result["findings"]]
            is_answered = cached_result.get("is_answered", True)
            res_tokens = TokenUsage()
            res_latency = 0.0
            tool_records.append(
                ToolCallRecord(
                    tool_name="idempotency_cache",
                    tool_input={"sub_question_id": sub_question.id},
                    tool_output_summary="Retrieved verified findings from idempotency cache.",
                    latency_ms=0.5,
                    status="success",
                )
            )
        else:
            collect_t0 = time.time()
            evidence_res = await collector.collect_evidence_for_queries(
                queries=queries,
                deep_scrape=(not is_mock_llm and deep_scrape_flag),
                focus_mode=focus_mode,
            )
            collect_latency = round((time.time() - collect_t0) * 1000, 2)
            evidence = evidence_res.formatted_context

            # Record empirical tool call telemetry
            tool_records.append(
                ToolCallRecord(
                    tool_name="web_search",
                    tool_input={"queries": queries},
                    tool_output_summary=f"Found {len(evidence_res.search_results)} search results across {len(queries)} queries.",
                    latency_ms=round(collect_latency * 0.4, 2),
                    status="success" if evidence_res.search_results else "no_results",
                )
            )
            if evidence_res.urls_processed:
                tool_records.append(
                    ToolCallRecord(
                        tool_name="page_scraper",
                        tool_input={
                            "urls_count": len(evidence_res.urls_processed),
                            "urls": evidence_res.urls_processed[:4],
                        },
                        tool_output_summary=f"Extracted {len(evidence_res.documents)} documents from {len(evidence_res.urls_processed)} candidate URLs.",
                        latency_ms=round(collect_latency * 0.6, 2),
                        status="success" if evidence_res.documents else "empty",
                    )
                )

            async with async_trace_span(
                name=f"agent.researcher.worker_{idx}",
                run_id=run_id,
                attributes={
                    "worker_index": idx,
                    "sub_question_id": sub_question.id,
                    "llm.model": str(res_model_name),
                    "search.queries_count": len(queries),
                    "scraped_docs_count": len(evidence_res.documents),
                },
            ) as res_span_ctx:
                output, res_tokens, res_latency = await research_subquestion(
                    sub_question=sub_question,
                    evidence_context=evidence,
                    llm=active_researcher_llm,
                    focus_mode=focus_mode,
                )
                findings = output.findings
                is_answered = output.is_answered
                res_cost = calculate_token_cost(
                    str(res_model_name), res_tokens.prompt_tokens, res_tokens.completion_tokens
                )
                res_tokens.estimated_cost_usd = res_cost

                res_span_ctx.update(
                    {
                        "findings_count": len(findings),
                        "is_answered": is_answered,
                        "tokens.total": res_tokens.total_tokens,
                        "cost.usd": res_cost,
                        "latency_ms": res_latency,
                    }
                )

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

        worker_tokens.add(
            res_tokens.prompt_tokens,
            res_tokens.completion_tokens,
            res_tokens.estimated_cost_usd,
        )
        worker_steps += 1
        trace_res = create_step_trace(
            step_number=step_res,
            agent_name="researcher",
            input_data={"sub_question_id": sub_question.id},
            output_data={"findings_count": len(findings), "is_answered": is_answered},
            tokens=res_tokens,
            latency_ms=res_latency,
            tool_calls=tool_records,
        )
        traces.append(trace_res)

        # 2. Reviewer evaluation
        async with async_trace_span(
            name=f"agent.reviewer.worker_{idx}",
            run_id=run_id,
            attributes={
                "worker_index": idx,
                "sub_question_id": sub_question.id,
                "llm.model": str(rev_model_name),
                "findings_count": len(findings),
            },
        ) as rev_span_ctx:
            evaluation, rev_tokens, rev_latency = await evaluate_research(
                sub_question=sub_question,
                findings=findings,
                llm=active_reviewer_llm,
            )
            rev_cost = calculate_token_cost(
                str(rev_model_name), rev_tokens.prompt_tokens, rev_tokens.completion_tokens
            )
            rev_tokens.estimated_cost_usd = rev_cost

            rev_span_ctx.update(
                {
                    "score": evaluation.quality_score,
                    "is_approved": evaluation.is_approved,
                    "feedback": evaluation.feedback[:120] if evaluation.feedback else "",
                    "tokens.total": rev_tokens.total_tokens,
                    "cost.usd": rev_cost,
                    "latency_ms": rev_latency,
                }
            )

        worker_tokens.add(
            rev_tokens.prompt_tokens,
            rev_tokens.completion_tokens,
            rev_tokens.estimated_cost_usd,
        )
        worker_steps += 1
        trace_rev = create_step_trace(
            step_number=step_rev,
            agent_name="reviewer",
            input_data={"sub_question_id": sub_question.id, "findings_count": len(findings)},
            output_data={
                "is_approved": evaluation.is_approved,
                "score": evaluation.quality_score,
                "feedback": evaluation.feedback,
            },
            tokens=rev_tokens,
            latency_ms=rev_latency,
        )
        traces.append(trace_rev)

        # 3. Single-pass revision gate if reviewer requested revision
        if not evaluation.is_approved:
            elapsed = (time.time() - start_time) if start_time > 0 else 0.0
            wall_limit = (
                float(max_wall_clock)
                if max_wall_clock
                else float(settings.MAX_WALL_CLOCK_SECONDS)
            )
            # If less than 20 seconds remain before hard ceiling, skip revision pass
            if start_time > 0 and (elapsed + 20.0 >= wall_limit):
                logger.warning(
                    "Worker skipping revision pass to preserve remaining wall-clock budget",
                    sub_question_id=sub_question.id,
                    elapsed=elapsed,
                    wall_limit=wall_limit,
                )
            else:
                logger.info(
                    "Worker executing single permitted revision", sub_question_id=sub_question.id
                )
                rev_queries = list(queries) + [f"{sub_question.question} {evaluation.feedback[:60]}"]
                rev_t0 = time.time()
                rev_evidence_res = await collector.collect_evidence_for_queries(
                    queries=rev_queries,
                    deep_scrape=(not is_mock_llm and deep_scrape_flag),
                    focus_mode=focus_mode,
                )
                rev_latency_ms = round((time.time() - rev_t0) * 1000, 2)
                rev_evidence = (
                    rev_evidence_res.formatted_context
                    + f"\n\nReviewer Feedback Guidance: {evaluation.feedback}\n"
                )

                rev_tool_records = [
                    ToolCallRecord(
                        tool_name="web_search_revision",
                        tool_input={"queries": rev_queries},
                        tool_output_summary=f"Found {len(rev_evidence_res.search_results)} supplementary sources.",
                        latency_ms=rev_latency_ms,
                        status="success",
                    )
                ]

                async with async_trace_span(
                    name=f"agent.researcher.revision_{idx}",
                    run_id=run_id,
                    attributes={
                        "worker_index": idx,
                        "sub_question_id": sub_question.id,
                        "revision": True,
                        "reviewer_feedback": evaluation.feedback[:100],
                    },
                ) as r2_span_ctx:
                    rev_output, r2_tokens, r2_latency = await research_subquestion(
                        sub_question=sub_question,
                        evidence_context=rev_evidence,
                        llm=active_researcher_llm,
                        focus_mode=focus_mode,
                    )
                    if rev_output.findings:
                        findings = rev_output.findings
                    r2_cost = calculate_token_cost(
                        str(res_model_name), r2_tokens.prompt_tokens, r2_tokens.completion_tokens
                    )
                    r2_tokens.estimated_cost_usd = r2_cost

                    r2_span_ctx.update(
                        {
                            "findings_count": len(findings),
                            "tokens.total": r2_tokens.total_tokens,
                            "cost.usd": r2_cost,
                            "latency_ms": r2_latency,
                        }
                    )

                worker_tokens.add(
                    r2_tokens.prompt_tokens,
                    r2_tokens.completion_tokens,
                    r2_tokens.estimated_cost_usd,
                )
                worker_steps += 1
                traces.append(
                    create_step_trace(
                        step_number=step_rev + 1,
                        agent_name="researcher",
                        input_data={"sub_question_id": sub_question.id, "revision": True},
                        output_data={"findings_count": len(findings)},
                        tokens=r2_tokens,
                        latency_ms=r2_latency,
                        tool_calls=rev_tool_records,
                    )
                )

        if run_manager and run_id:
            try:
                await run_manager.record_completed_step(
                    run_id=run_id,
                    node_name="researcher",
                    step_number=step_res,
                )
            except Exception as e:
                logger.debug("Failed updating run_manager in worker", error=str(e))

        return {
            "findings": findings,
            "audit_traces": traces,
            "total_tokens": worker_tokens,
            "step_count": worker_steps,
        }

    async def consolidator_node(state: ResearchState) -> dict[str, Any]:
        findings = _normalize_findings(state.get("findings", []))
        cum_tokens = _normalize_tokens(state.get("total_tokens"))
        run_id = state.get("run_id", "")
        plan = _normalize_plan(state.get("plan"))
        sub_count = len(plan.sub_questions) if plan else 0

        logger.info(
            "Consolidator joined all parallel research workers",
            total_findings=len(findings),
            total_tokens=cum_tokens.total_tokens,
        )

        async with async_trace_span(
            name="graph.consolidator",
            run_id=run_id,
            attributes={
                "total_findings": len(findings),
                "total_tokens": cum_tokens.total_tokens,
                "sub_questions_count": sub_count,
            },
        ):
            budget = evaluate_budget(state)
            is_resource_breached = budget.is_exceeded and budget.exceeded_metric in (
                "tokens",
                "wall_clock",
            )
            if is_resource_breached:
                new_status = "budget_exceeded"
            elif can_attempt_gap_fill(state) and plan and plan.sub_questions:
                unanswered = [
                    sq.id
                    for sq in plan.sub_questions
                    if not [
                        f
                        for f in findings
                        if getattr(f, "sub_question_id", None) == sq.id
                        or (isinstance(f, dict) and f.get("sub_question_id") == sq.id)
                    ]
                ]
                new_status = "gap_filling" if (unanswered or not findings) else "writing"
            else:
                new_status = "writing"

        if run_manager and run_id:
            try:
                await run_manager.update_run_status(
                    run_id=run_id,
                    status=new_status,
                    current_node="consolidator",
                    step_count=state.get("step_count", 0) + 1,
                    total_tokens=cum_tokens.total_tokens,
                )
                await run_manager.record_completed_step(
                    run_id=run_id,
                    node_name="consolidator",
                    step_number=state.get("step_count", 0) + 1,
                )
            except Exception as e:
                logger.debug("Failed updating run_manager in consolidator", error=str(e))

        return {
            "status": new_status,
            "current_sub_question_index": sub_count,
            "step_count": 1,
        }

    async def gap_filler_node(state: ResearchState) -> dict[str, Any]:
        step = state.get("step_count", 0) + 1
        run_id = state.get("run_id", "")
        query = state.get("query", "")
        plan = _normalize_plan(state.get("plan"))
        findings = _normalize_findings(state.get("findings", []))
        deep_scrape_pref = state.get("deep_scrape", True)
        focus_mode = state.get("focus_mode", "general")

        # 1. Identify which sub-questions currently lack empirical findings
        unanswered_subqs = []
        if plan and plan.sub_questions:
            for sq in plan.sub_questions:
                sq_f = [
                    f
                    for f in findings
                    if getattr(f, "sub_question_id", None) == sq.id
                    or (isinstance(f, dict) and f.get("sub_question_id") == sq.id)
                ]
                if not sq_f:
                    unanswered_subqs.append(sq)

        target_subq = (
            unanswered_subqs[0]
            if unanswered_subqs
            else (
                plan.sub_questions[0]
                if (plan and plan.sub_questions)
                else SubQuestion(
                    id="gap_1",
                    question=query,
                    rationale="Fallback targeted query to resolve knowledge gaps",
                    search_queries=[query],
                )
            )
        )

        logger.info(
            "Executing Deep Research Gap-Filler specialist",
            target_sub_question_id=target_subq.id,
            target_question=target_subq.question,
            step=step,
        )

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

        # Build fallback search queries designed to find authoritative overview documentation
        clean_q = re.sub(r"[^\w\s]", " ", target_subq.question).strip()
        gap_queries = [
            f"{clean_q} overview documentation",
            f"{target_subq.question}",
        ]
        if target_subq.search_queries:
            gap_queries.append(target_subq.search_queries[0])

        gap_model_name = (
            getattr(active_researcher_llm, "model_name", None)
            or getattr(active_researcher_llm, "model", None)
            or "default"
        )

        collect_t0 = time.time()
        evidence_res = await collector.collect_evidence_for_queries(
            queries=gap_queries[:2],
            deep_scrape=bool(not is_mock_llm and deep_scrape_pref),
            focus_mode=focus_mode,
        )
        collect_latency = round((time.time() - collect_t0) * 1000, 2)
        evidence = evidence_res.formatted_context

        tool_records = [
            ToolCallRecord(
                tool_name="web_search_gap_filler",
                tool_input={"queries": gap_queries[:2]},
                tool_output_summary=f"Discovered {len(evidence_res.search_results)} supplementary recovery results.",
                latency_ms=round(collect_latency * 0.4, 2),
                status="success" if evidence_res.search_results else "no_results",
            )
        ]
        if evidence_res.urls_processed:
            tool_records.append(
                ToolCallRecord(
                    tool_name="page_scraper_gap_filler",
                    tool_input={"urls": evidence_res.urls_processed[:3]},
                    tool_output_summary=f"Extracted {len(evidence_res.documents)} documents during gap recovery pass.",
                    latency_ms=round(collect_latency * 0.6, 2),
                    status="success" if evidence_res.documents else "empty",
                )
            )

        async with async_trace_span(
            name="agent.gap_filler",
            run_id=run_id,
            attributes={
                "target_sub_question_id": target_subq.id,
                "llm.model": str(gap_model_name),
                "queries_count": len(gap_queries[:2]),
            },
        ) as gap_span_ctx:
            output, gap_tokens, gap_latency = await research_subquestion(
                sub_question=target_subq,
                evidence_context=evidence,
                llm=active_researcher_llm,
                focus_mode=focus_mode,
            )
            new_findings = output.findings
            for nf in new_findings:
                if not getattr(nf, "sub_question_id", None):
                    nf.sub_question_id = target_subq.id

            gap_cost = calculate_token_cost(
                str(gap_model_name), gap_tokens.prompt_tokens, gap_tokens.completion_tokens
            )
            gap_tokens.estimated_cost_usd = gap_cost

            gap_span_ctx.update(
                {
                    "recovered_findings_count": len(new_findings),
                    "tokens.total": gap_tokens.total_tokens,
                    "cost.usd": gap_cost,
                    "latency_ms": gap_latency,
                }
            )

        trace = create_step_trace(
            step_number=step,
            agent_name="gap_filler",
            input_data={
                "target_sub_question_id": target_subq.id,
                "gap_queries": gap_queries[:2],
            },
            output_data={
                "recovered_findings_count": len(new_findings),
                "is_answered": output.is_answered,
            },
            tokens=gap_tokens,
            latency_ms=gap_latency,
            tool_calls=tool_records,
        )

        remaining_unresolved = [
            sq.id for sq in unanswered_subqs if sq.id != target_subq.id
        ]
        if not new_findings:
            remaining_unresolved.append(target_subq.id)

        if run_manager and run_id:
            try:
                await run_manager.record_completed_step(
                    run_id=run_id,
                    node_name="gap_filler",
                    step_number=step,
                )
            except Exception as e:
                logger.debug("Failed updating run_manager in gap_filler", error=str(e))

        current_attempts = state.get("gap_fill_attempts", 0)
        return {
            "findings": new_findings,
            "gap_fill_attempts": current_attempts + 1,
            "unresolved_gaps": remaining_unresolved,
            "step_count": 1,
            "total_tokens": gap_tokens,
            "audit_traces": [trace],
        }

    async def writer_node(state: ResearchState) -> dict[str, Any]:
        step = state.get("step_count", 0) + 1
        query = state.get("query", "")
        run_id = state.get("run_id", "")
        findings = _normalize_findings(state.get("findings", []))
        focus_mode = state.get("focus_mode", "general")
        logger.info("Executing Writer node", step=step, findings_count=len(findings), focus_mode=focus_mode)

        writer_model = (
            getattr(active_writer_llm, "model_name", None)
            or getattr(active_writer_llm, "model", None)
            or "default"
        )
        try:
            async with async_trace_span(
                name="agent.writer",
                run_id=run_id,
                attributes={
                    "step": step,
                    "agent.role": "writer",
                    "findings_count": len(findings),
                    "llm.model": str(writer_model),
                },
            ) as span_ctx:
                report, tokens, latency = await write_report(
                    query=query,
                    findings=findings,
                    llm=active_writer_llm,
                    focus_mode=focus_mode,
                )
                writer_cost = calculate_token_cost(
                    str(writer_model), tokens.prompt_tokens, tokens.completion_tokens
                )
                tokens.estimated_cost_usd = writer_cost

                span_ctx.update(
                    {
                        "title": report.title,
                        "sections_count": len(report.sections),
                        "citations_count": len(report.citations),
                        "tokens.prompt": tokens.prompt_tokens,
                        "tokens.completion": tokens.completion_tokens,
                        "tokens.total": tokens.total_tokens,
                        "cost.usd": writer_cost,
                        "latency_ms": latency,
                    }
                )

                trace = create_step_trace(
                    step_number=step,
                    agent_name="writer",
                    input_data={"query": query, "findings_count": len(findings)},
                    output_data={"title": report.title, "sections_count": len(report.sections)},
                    tokens=tokens,
                    latency_ms=latency,
                )

            cum_tokens = _normalize_tokens(state.get("total_tokens"))
            cum_tokens.add(tokens.prompt_tokens, tokens.completion_tokens, tokens.estimated_cost_usd)

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
                "step_count": 1,
                "total_tokens": tokens,
                "audit_traces": [trace],
            }
        except Exception as exc:
            classified = classify_error(
                exc,
                model_name=str(writer_model) if writer_model else None,
                node="writer",
            )
            logger.error(
                "Writer node execution failed",
                run_id=run_id,
                code=classified.code,
                error=classified.message,
            )
            raise classified from exc

    async def emergency_writer_node(state: ResearchState) -> dict[str, Any]:
        step = state.get("step_count", 0) + 1
        query = state.get("query", "")
        run_id = state.get("run_id", "")
        findings = _normalize_findings(state.get("findings", []))
        logger.warning("Executing Emergency Writer node (budget ceiling breached)", step=step)

        async with async_trace_span(
            name="agent.emergency_writer",
            run_id=run_id,
            attributes={
                "reason": "budget_exceeded",
                "findings_count": len(findings),
            },
        ):
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
                    Citation(
                        citation_id=f"[cite_{i}]",
                        source_url=f.source_url,
                        verified_claim=f.claim,
                    )
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
            "step_count": 1,
            "audit_traces": [trace],
        }

    builder = StateGraph(ResearchState)  # type: ignore[arg-type]

    # Register nodes
    builder.add_node("planner", planner_node)
    builder.add_node("plan_gate", plan_gate_node)
    builder.add_node("researcher", researcher_node)  # type: ignore[arg-type]
    builder.add_node("consolidator", consolidator_node)
    builder.add_node("gap_filler", gap_filler_node)
    builder.add_node("writer", writer_node)
    builder.add_node("emergency_writer", emergency_writer_node)

    # Connect edges
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "plan_gate")
    builder.add_conditional_edges(
        "plan_gate",
        route_after_plan_gate,
        {
            "researcher": "researcher",
            "planner": "planner",
            "failed": END,
        },
    )
    builder.add_edge("researcher", "consolidator")
    builder.add_conditional_edges(
        "consolidator",
        route_after_consolidator,
        {
            "writer": "writer",
            "gap_filler": "gap_filler",
            "emergency_writer": "emergency_writer",
            "failed": END,
        },
    )
    builder.add_edge("gap_filler", "consolidator")
    builder.add_edge("writer", END)
    builder.add_edge("emergency_writer", END)

    return builder


def compile_research_graph(
    llm: BaseChatModel | None = None,
    llm_planner: BaseChatModel | None = None,
    llm_researcher: BaseChatModel | None = None,
    llm_reviewer: BaseChatModel | None = None,
    llm_writer: BaseChatModel | None = None,
    checkpointer: Any = None,
    evidence_collector: EvidenceCollector | None = None,
    run_manager: Any = None,
    idempotency_cache: Any = None,
):
    """Build and compile the research graph ready for execution."""
    builder = build_research_graph(
        llm=llm,
        llm_planner=llm_planner,
        llm_researcher=llm_researcher,
        llm_reviewer=llm_reviewer,
        llm_writer=llm_writer,
        evidence_collector=evidence_collector,
        run_manager=run_manager,
        idempotency_cache=idempotency_cache,
    )
    return builder.compile(checkpointer=checkpointer)


def create_initial_state(
    query: str,
    run_id: str | None = None,
    max_sub_questions: int | None = None,
    max_wall_clock_seconds: float | None = None,
    max_tokens: int | None = None,
    deep_scrape: bool = True,
    focus_mode: str = "general",
    hitl_enabled: bool = False,
) -> ResearchState:
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
        gap_fill_attempts=0,
        unresolved_gaps=[],
        report=None,
        status="planning",
        total_tokens=TokenUsage(),
        start_time=time.time(),
        step_count=0,
        audit_traces=[],
        max_sub_questions=max_sub_questions,
        max_wall_clock_seconds=max_wall_clock_seconds,
        max_tokens=max_tokens,
        deep_scrape=deep_scrape,
        focus_mode=focus_mode,
        hitl_enabled=hitl_enabled,
        plan_approved=False,
        steering_feedback=None,
        error_message=None,
    )
