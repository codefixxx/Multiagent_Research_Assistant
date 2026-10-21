"""Background job execution engine for the multi-agent research workflow."""

import asyncio
import time
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

from src.api.events import EventBroadcaster, broadcaster
from src.config import settings
from src.core.exceptions import classify_error
from src.core.llm import detect_provider, get_chat_model
from src.core.logger import logger
from src.core.telemetry import RunCostSummary, StageCostAttribution, TokenUsage
from src.core.tracer import get_run_spans
from src.graph.builder import _normalize_tokens, compile_research_graph, create_initial_state
from src.persistence.queue import RedisJobQueue
from src.persistence.redis_saver import (
    NodeIdempotencyCache,
    RedisRunManager,
    get_checkpointer,
    get_redis_client,
)
from src.schemas.api import AuditTraceResponse, ResearchRequest, ResearchStatusResponse
from src.schemas.finding import FindingRecord
from src.schemas.report import ResearchReport
from src.schemas.trace import AuditLog, StepTrace
from src.validators.citation_validator import (
    CitationValidationResult,
    validate_report_citations_async,
)
from src.validators.rag_scorer import RAGQualityScore, calculate_rag_quality_score


def _unwrap_lc(d: Any) -> Any:
    """Recursively unwrap LangChain serialized dict structures (lc=2, kwargs)."""
    if isinstance(d, dict):
        if d.get("lc") == 2 and "kwargs" in d:
            return _unwrap_lc(d["kwargs"])
        return {k: _unwrap_lc(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_unwrap_lc(x) for x in d]
    return d


class ResearchJobService:
    """Manages background research runs, LangGraph execution, and state persistence."""

    def __init__(
        self,
        run_manager: RedisRunManager | None = None,
        event_broadcaster: EventBroadcaster | None = None,
        idempotency_cache: NodeIdempotencyCache | None = None,
        checkpointer: Any = None,
        llm: BaseChatModel | None = None,
        queue: RedisJobQueue | None = None,
    ) -> None:
        self.run_manager = run_manager
        self.broadcaster = event_broadcaster or broadcaster
        self.idempotency_cache = idempotency_cache
        self.checkpointer = checkpointer
        self.default_llm = llm
        self.queue = queue
        self._active_tasks: dict[str, asyncio.Task[Any]] = {}

    async def initialize(self, force_new: bool = False, force_fake: bool = False) -> None:
        """Initialize Redis connection and dependencies if not already supplied or loop changed."""
        is_stale = False
        try:
            curr_loop = asyncio.get_running_loop()
            saved_loop = getattr(self, "_current_loop", None)
            if saved_loop is not None and (saved_loop is not curr_loop or saved_loop.is_closed()):
                is_stale = True
        except Exception:
            is_stale = True

        if self.run_manager is None or self.queue is None or force_new or is_stale:
            client = await get_redis_client(force_fake=force_fake)
            try:
                self._current_loop = asyncio.get_running_loop()
            except Exception:
                self._current_loop = None
            if self.run_manager is None or force_new:
                self.run_manager = RedisRunManager(client)
            if self.idempotency_cache is None or force_new:
                self.idempotency_cache = NodeIdempotencyCache(client)
            if self.checkpointer is None or force_new:
                self.checkpointer = await get_checkpointer(client)
            if self.queue is None or force_new:
                self.queue = RedisJobQueue(client)
            await self.broadcaster.initialize(client)

    async def start_job(
        self,
        run_id: str,
        request: ResearchRequest,
        llm_override: BaseChatModel | None = None,
        mode: str | None = None,
    ) -> None:
        """Schedule and launch a research job (via decoupled Redis queue or in-process task)."""
        await self.initialize()

        assert self.run_manager is not None
        # Initialize run metadata in Redis
        await self.run_manager.init_run(run_id=run_id, query=request.query)

        effective_mode = mode or settings.WORKER_MODE

        # When running in decoupled mode, enqueue job payload onto Redis queue
        # for background worker execution (<10ms).
        if effective_mode == "decoupled":
            assert self.queue is not None
            await self.queue.enqueue(run_id=run_id, request=request)
            await self.broadcaster.broadcast(
                run_id=run_id,
                event="job_queued",
                data={
                    "query": request.query,
                    "status": "queued",
                    "message": "Research job queued and dispatched to distributed worker.",
                },
            )
            logger.info("Dispatched research job to Redis queue", run_id=run_id)
            return

        # Embedded / In-process execution mode:
        await self.broadcaster.broadcast(
            run_id=run_id,
            event="job_queued",
            data={
                "query": request.query,
                "status": "queued",
                "message": "Research job queued and dispatching.",
            },
        )

        task = asyncio.create_task(
            self._execute_job(
                run_id=run_id,
                request=request,
                llm=llm_override or self.default_llm,
            ),
            name=f"research_job_{run_id}",
        )
        self._active_tasks[run_id] = task

        # Add done callback to clean up task reference
        def _cleanup(t: asyncio.Task[Any]) -> None:
            self._active_tasks.pop(run_id, None)

        task.add_done_callback(_cleanup)

    async def _execute_job(
        self,
        run_id: str,
        request: ResearchRequest,
        llm: BaseChatModel | None = None,
    ) -> None:
        """Internal worker executing the LangGraph state machine with full telemetry."""
        logger.info(
            "Starting background research run execution", run_id=run_id, query=request.query
        )
        start_time = time.time()

        assert self.run_manager is not None

        try:
            # Resolve specialized models for each agent role if not provided by caller (e.g. tests)
            llm_planner = None
            llm_researcher = None
            llm_reviewer = None
            llm_writer = None
            collector = None

            if llm is None:
                user_keys = request.api_keys.model_dump() if request.api_keys else {}
                matrix = request.model_matrix.model_dump() if request.model_matrix else {}

                def _get_key_for_model(model_name: str | None) -> str | None:
                    if not model_name:
                        return None
                    prov = detect_provider(model_name)
                    return user_keys.get(prov)

                planner_model = matrix.get("planner")
                researcher_model = matrix.get("researcher")
                reviewer_model = matrix.get("reviewer")
                writer_model = matrix.get("writer")

                llm_planner = get_chat_model(
                    model_name=planner_model,
                    api_key=_get_key_for_model(planner_model),
                    temperature=0.0,
                )
                llm_researcher = get_chat_model(
                    model_name=researcher_model,
                    api_key=_get_key_for_model(researcher_model),
                    temperature=0.1,
                )
                llm_reviewer = get_chat_model(
                    model_name=reviewer_model,
                    api_key=_get_key_for_model(reviewer_model),
                    temperature=0.0,
                )
                llm_writer = get_chat_model(
                    model_name=writer_model,
                    api_key=_get_key_for_model(writer_model),
                    temperature=0.2,
                )

                tavily_user_key = user_keys.get("tavily")
                if tavily_user_key:
                    from src.tools.evidence_collector import EvidenceCollector
                    from src.tools.search import MultiSearchClient, TavilySearchClient

                    collector = EvidenceCollector(
                        search_client=MultiSearchClient(
                            tavily_client=TavilySearchClient(api_key=tavily_user_key)
                        )
                    )

            # Compile the graph bound to this run's persistence checkpointer
            graph = compile_research_graph(
                llm=llm,
                llm_planner=llm_planner,
                llm_researcher=llm_researcher,
                llm_reviewer=llm_reviewer,
                llm_writer=llm_writer,
                evidence_collector=collector,
                checkpointer=self.checkpointer,
                run_manager=self.run_manager,
                idempotency_cache=self.idempotency_cache,
            )

            initial_state = create_initial_state(
                query=request.query,
                run_id=run_id,
                max_sub_questions=request.max_sub_questions,
                max_wall_clock_seconds=request.max_wall_clock_seconds,
                max_tokens=request.max_tokens,
                deep_scrape=request.deep_scrape,
            )
            config: RunnableConfig = {"configurable": {"thread_id": run_id}}

            merged_state: dict[str, Any] = dict(initial_state)

            await self.broadcaster.broadcast(
                run_id=run_id,
                event="job_started",
                data={
                    "status": "planning",
                    "message": "Orchestrator started: generating research plan.",
                },
            )

            async for chunk in graph.astream(initial_state, config=config, stream_mode="updates"):
                if self.queue and await self.queue.is_cancelled(run_id):
                    logger.warning("Research job cancelled via Redis flag", run_id=run_id)
                    await self.run_manager.update_run_status(
                        run_id=run_id,
                        status="cancelled",
                        error_message="Job execution cancelled by caller.",
                    )
                    await self.broadcaster.broadcast(
                        run_id=run_id,
                        event="job_failed",
                        data={"status": "cancelled", "error": "Job cancelled."},
                    )
                    return
                for node_name, node_output in chunk.items():
                    # Preserve findings list accumulation across parallel workers
                    if "findings" in node_output and node_output["findings"]:
                        existing_findings = list(merged_state.get("findings", []))
                        merged_state["findings"] = existing_findings + list(node_output["findings"])
                    for k, v in node_output.items():
                        if k != "findings":
                            merged_state[k] = v

                    # Dispatch event based on which agent just finished
                    if node_name == "planner":
                        plan = node_output.get("plan")
                        sub_questions = getattr(plan, "sub_questions", []) if plan else []
                        await self.broadcaster.broadcast(
                            run_id=run_id,
                            event="planner_completed",
                            data={
                                "node": "planner",
                                "status": "researching",
                                "sub_questions_count": len(sub_questions),
                                "sub_questions": [
                                    sq.model_dump(mode="json") if hasattr(sq, "model_dump") else sq
                                    for sq in sub_questions
                                ],
                                "plan": plan.model_dump(mode="json") if hasattr(plan, "model_dump") else plan,
                                "objective": getattr(plan, "objective", ""),
                            },
                        )

                    elif node_name == "researcher":
                        findings = merged_state.get("findings", [])
                        new_findings = node_output.get("current_sub_question_findings", [])
                        if not new_findings and "findings" in node_output:
                            new_findings = node_output.get("findings", [])
                        subq_id = node_output.get("sub_question_id")
                        if not subq_id and new_findings and len(new_findings) > 0:
                            first_f = new_findings[0]
                            subq_id = getattr(first_f, "sub_question_id", None) or (
                                first_f.get("sub_question_id") if isinstance(first_f, dict) else None
                            )
                        is_approved = node_output.get("is_approved", True)
                        is_revision = node_output.get("is_revision", False)

                        await self.broadcaster.broadcast(
                            run_id=run_id,
                            event="researching_subquestion",
                            data={
                                "node": "researcher",
                                "status": "researching",
                                "sub_question_id": subq_id,
                                "new_findings_count": len(new_findings),
                                "total_findings_count": len(findings),
                                "is_revision": is_revision,
                            },
                        )
                        if subq_id:
                            await self.broadcaster.broadcast(
                                run_id=run_id,
                                event="subquestion_reviewed",
                                data={
                                    "node": "reviewer",
                                    "sub_question_id": subq_id,
                                    "is_approved": is_approved,
                                    "is_revision": is_revision,
                                },
                            )

                    elif node_name == "consolidator":
                        findings = merged_state.get("findings", [])
                        current_status = node_output.get("status", "writing")
                        await self.broadcaster.broadcast(
                            run_id=run_id,
                            event="consolidator_completed",
                            data={
                                "node": "consolidator",
                                "status": current_status,
                                "total_findings_count": len(findings),
                            },
                        )

                    elif node_name == "gap_filler":
                        findings = merged_state.get("findings", [])
                        new_findings = node_output.get("findings", [])
                        unresolved = node_output.get("unresolved_gaps", [])
                        await self.broadcaster.broadcast(
                            run_id=run_id,
                            event="gap_filler_completed",
                            data={
                                "node": "gap_filler",
                                "status": "researching",
                                "new_findings_count": len(new_findings),
                                "total_findings_count": len(findings),
                                "unresolved_gaps": unresolved,
                            },
                        )

                    elif node_name == "writer":
                        report: ResearchReport | None = node_output.get("report")
                        await self.broadcaster.broadcast(
                            run_id=run_id,
                            event="writing_completed",
                            data={
                                "node": "writer",
                                "status": "completed",
                                "title": report.title if report else "",
                                "sections_count": len(report.sections) if report else 0,
                                "citations_count": len(report.citations) if report else 0,
                            },
                        )

                    elif node_name == "emergency_writer":
                        report = node_output.get("report")
                        await self.broadcaster.broadcast(
                            run_id=run_id,
                            event="budget_exceeded",
                            data={
                                "node": "emergency_writer",
                                "status": "budget_exceeded",
                                "title": report.title if report else "",
                            },
                        )

            # Query canonical state from graph checkpointer to ensure 100% of parallel worker findings are present
            try:
                final_snapshot = await graph.aget_state(config)
                if final_snapshot and final_snapshot.values:
                    cvals = final_snapshot.values
                    # Keep existing ResearchReport if already instantiated; otherwise use canonical
                    if cvals.get("report") and not isinstance(merged_state.get("report"), ResearchReport):
                        merged_state["report"] = cvals["report"]
                    if cvals.get("findings"):
                        existing_urls = {
                            getattr(f, "source_url", None) or (f.get("source_url") if isinstance(f, dict) else None)
                            for f in merged_state.get("findings", [])
                        }
                        for cf in cvals["findings"]:
                            cf_url = getattr(cf, "source_url", None) or (cf.get("source_url") if isinstance(cf, dict) else None)
                            if cf_url not in existing_urls:
                                merged_state.setdefault("findings", []).append(cf)
                    if cvals.get("status"):
                        merged_state["status"] = cvals["status"]
            except Exception as e:
                logger.debug("Failed querying canonical checkpointer state", error=str(e))

            final_status = merged_state.get("status", "completed")
            raw_report = merged_state.get("report")
            findings_list = merged_state.get("findings", [])

            # Deserialization & unwrapping if wrapped in LangChain serializations
            if isinstance(raw_report, dict):
                raw_report = ResearchReport.model_validate(_unwrap_lc(raw_report))

            findings_obj_list: list[FindingRecord] = []
            for f in findings_list:
                if isinstance(f, FindingRecord):
                    findings_obj_list.append(f)
                elif isinstance(f, dict):
                    findings_obj_list.append(FindingRecord.model_validate(_unwrap_lc(f)))

            # Run Pre-flight Citation Validation with live HTTP verification and text fragments
            citation_validation: CitationValidationResult | None = None
            final_report: ResearchReport | None = None
            if raw_report and isinstance(raw_report, ResearchReport):
                citation_validation = await validate_report_citations_async(
                    report=raw_report,
                    findings=findings_obj_list,
                    auto_sanitize=True,
                    probe_http=True,
                )
                final_report = citation_validation.sanitized_report

            # Persist Report in Redis
            if final_report is not None:
                report_dict: dict[str, Any] = final_report.model_dump(mode="json")
                await self.run_manager.save_report(run_id=run_id, report_data=report_dict)

            # Assemble Spans, Cost Attribution, and RAG Quality Score
            spans = get_run_spans(run_id)
            raw_traces = merged_state.get("audit_traces", [])
            step_traces = [
                t if isinstance(t, StepTrace) else StepTrace.model_validate(t) for t in raw_traces
            ]
            total_tokens = _normalize_tokens(merged_state.get("total_tokens"))
            total_latency = (time.time() - start_time) * 1000.0

            # Calculate StageCostAttribution and RunCostSummary
            cost_summary = RunCostSummary()
            for st in step_traces:
                st_key = f"{st.agent_name}_{st.step_number}"
                cost_summary.add_stage(
                    StageCostAttribution(
                        stage_name=st_key,
                        agent_role=st.agent_name,
                        prompt_tokens=st.token_usage.prompt_tokens,
                        completion_tokens=st.token_usage.completion_tokens,
                        total_tokens=st.token_usage.total_tokens,
                        cost_usd=st.token_usage.estimated_cost_usd,
                        latency_ms=st.latency_ms,
                    )
                )

            # Calculate automated RAG Quality Score
            rag_score = calculate_rag_quality_score(
                report=final_report,
                findings=findings_obj_list,
                validation_result=citation_validation,
                plan=merged_state.get("plan"),
            )

            audit_log = AuditLog(
                run_id=run_id,
                query=request.query,
                steps=step_traces,
                total_token_usage=total_tokens,
                total_latency_ms=total_latency,
                status=final_status,
                cost_summary=cost_summary.model_dump(mode="json"),
                rag_score=rag_score.model_dump(mode="json"),
                spans=spans,
            )
            await self.run_manager.save_audit_log(
                run_id=run_id,
                audit_data=audit_log.model_dump(mode="json"),
            )

            # Update final metadata in Redis
            await self.run_manager.update_run_status(
                run_id=run_id,
                status=final_status,
                current_node="done",
                step_count=merged_state.get("step_count", len(step_traces)),
                total_tokens=total_tokens.total_tokens,
                cost_summary=cost_summary.model_dump(mode="json"),
                rag_score=rag_score.model_dump(mode="json"),
            )

            # Broadcast final completion event
            await self.broadcaster.broadcast(
                run_id=run_id,
                event="job_completed" if final_status == "completed" else "budget_exceeded",
                data={
                    "status": final_status,
                    "title": final_report.title if final_report else "",
                    "report": final_report.model_dump(mode="json") if final_report else None,
                    "findings_count": len(findings_obj_list),
                    "total_tokens": total_tokens.total_tokens,
                    "latency_ms": total_latency,
                    "citations_verified": (
                        len(citation_validation.verified_citations) if citation_validation else 0
                    ),
                    "citations_hallucinated": (
                        len(citation_validation.hallucinated_citations)
                        if citation_validation
                        else 0
                    ),
                    "citation_validation": citation_validation.model_dump(mode="json") if citation_validation else None,
                    "cost_summary": cost_summary.model_dump(mode="json"),
                    "rag_score": rag_score.model_dump(mode="json"),
                    "spans_count": len(spans),
                },
            )
            await self.run_manager.apply_ttl(run_id)
            logger.info(
                "Research job execution finished successfully", run_id=run_id, status=final_status
            )

        except asyncio.CancelledError:
            logger.warning("Research job was cancelled", run_id=run_id)
            await self.run_manager.update_run_status(
                run_id=run_id,
                status="cancelled",
                error_message="Job execution cancelled by caller.",
            )
            await self.run_manager.apply_ttl(run_id)
            await self.broadcaster.broadcast(
                run_id=run_id,
                event="job_failed",
                data={"status": "cancelled", "error": "Job cancelled."},
            )
            raise

        except Exception as e:
            app_err = classify_error(e)
            logger.error(
                "Research job execution failed",
                run_id=run_id,
                code=app_err.code,
                error=app_err.message,
                suggestion=app_err.suggestion,
                details=app_err.details,
            )
            await self.run_manager.update_run_status(
                run_id=run_id,
                status="failed",
                error_message=app_err.message,
                error_code=app_err.code,
                error_suggestion=app_err.suggestion,
                error_details=app_err.details,
            )
            # Assemble failure audit log so /trace endpoint provides diagnostic info
            try:
                spans = get_run_spans(run_id)
                failed_audit_log = AuditLog(
                    run_id=run_id,
                    query=request.query,
                    steps=[],
                    total_token_usage=TokenUsage(),
                    total_latency_ms=(time.time() - start_time) * 1000.0,
                    status="failed",
                    spans=spans,
                    error=f"[{app_err.code}] {app_err.message}",
                )
                await self.run_manager.save_audit_log(
                    run_id=run_id,
                    audit_data=failed_audit_log.model_dump(mode="json"),
                )
            except Exception as audit_exc:
                logger.debug("Failed saving failure audit log", error=str(audit_exc))

            await self.run_manager.apply_ttl(run_id)
            await self.broadcaster.broadcast(
                run_id=run_id,
                event="job_failed",
                data={
                    "status": "failed",
                    "error": app_err.message,
                    "code": app_err.code,
                    "suggestion": app_err.suggestion,
                    "details": app_err.details,
                },
            )

    async def get_status(self, run_id: str) -> ResearchStatusResponse | None:
        """Fetch current status and report (if completed) for a given run ID."""
        await self.initialize()
        assert self.run_manager is not None

        meta = await self.run_manager.get_run_metadata(run_id)
        if not meta:
            return None

        status = meta.get("status", "planning")
        current_node = meta.get("current_node")

        # Estimate progress percentage based on node lifecycle
        progress_pct = 10
        if status == "planning":
            progress_pct = 20
        elif status == "researching":
            step = meta.get("step_count", 1)
            progress_pct = min(80, 25 + (step * 12))
        elif status == "reviewing":
            progress_pct = 75
        elif status == "writing":
            progress_pct = 90
        elif status in ("completed", "budget_exceeded"):
            progress_pct = 100
        elif status in ("failed", "cancelled"):
            progress_pct = 100

        # Retrieve report if finished
        report_obj: ResearchReport | None = None
        raw_report = await self.run_manager.get_report(run_id)
        if raw_report:
            report_obj = ResearchReport.model_validate(raw_report)

        findings_count = len(report_obj.citations) if report_obj and report_obj.citations else 0
        raw_audit = await self.run_manager.get_audit_log(run_id)
        if raw_audit and isinstance(raw_audit, dict):
            try:
                for s in raw_audit.get("steps", []):
                    if s.get("agent_name") == "researcher":
                        findings_count = max(findings_count, s.get("output_data", {}).get("findings_count", 0))
            except Exception:
                pass

        cost_summary_dict = meta.get("cost_summary") or (
            raw_audit.get("cost_summary") if raw_audit and isinstance(raw_audit, dict) else None
        )
        rag_score_dict = meta.get("rag_score") or (
            raw_audit.get("rag_score") if raw_audit and isinstance(raw_audit, dict) else None
        )

        return ResearchStatusResponse(
            run_id=run_id,
            query=meta.get("query", ""),
            status=status,
            progress_pct=progress_pct,
            current_node=current_node,
            step_count=meta.get("step_count", 0),
            total_tokens=meta.get("total_tokens", 0),
            findings_count=findings_count,
            report=report_obj,
            cost_summary=RunCostSummary.model_validate(cost_summary_dict)
            if cost_summary_dict
            else None,
            rag_score=RAGQualityScore.model_validate(rag_score_dict)
            if rag_score_dict
            else None,
            error_message=meta.get("error_message"),
            error_code=meta.get("error_code"),
            error_suggestion=meta.get("error_suggestion"),
            error_details=meta.get("error_details"),
            created_at=meta.get("created_at"),
            updated_at=meta.get("updated_at"),
        )

    async def get_audit_trace(self, run_id: str) -> AuditTraceResponse | None:
        """Retrieve the complete audit trail and step-by-step metrics for a run."""
        await self.initialize()
        assert self.run_manager is not None

        live_spans = get_run_spans(run_id)
        raw_audit = await self.run_manager.get_audit_log(run_id)
        meta = await self.run_manager.get_run_metadata(run_id) or {}

        if raw_audit:
            audit = AuditLog.model_validate(raw_audit)
            effective_spans = audit.spans or live_spans
            cost_dict = audit.cost_summary or meta.get("cost_summary")
            rag_dict = audit.rag_score or meta.get("rag_score")
            return AuditTraceResponse(
                run_id=run_id,
                query=audit.query,
                status=audit.status,
                total_latency_ms=audit.total_latency_ms,
                total_tokens=audit.total_token_usage,
                step_count=len(audit.steps),
                steps=audit.steps,
                cost_summary=RunCostSummary.model_validate(cost_dict) if cost_dict else None,
                rag_score=RAGQualityScore.model_validate(rag_dict) if rag_dict else None,
                spans=effective_spans,
                error=audit.error or meta.get("error_message"),
                error_code=meta.get("error_code"),
                error_suggestion=meta.get("error_suggestion"),
            )

        if not meta:
            return None

        cost_dict = meta.get("cost_summary")
        rag_dict = meta.get("rag_score")
        return AuditTraceResponse(
            run_id=run_id,
            query=meta.get("query", ""),
            status=meta.get("status", "planning"),
            total_latency_ms=0.0,
            total_tokens=TokenUsage(total_tokens=meta.get("total_tokens", 0)),
            step_count=meta.get("step_count", 0),
            steps=[],
            cost_summary=RunCostSummary.model_validate(cost_dict) if cost_dict else None,
            rag_score=RAGQualityScore.model_validate(rag_dict) if rag_dict else None,
            spans=live_spans,
            error=meta.get("error_message"),
            error_code=meta.get("error_code"),
            error_suggestion=meta.get("error_suggestion"),
        )

    async def cancel_job(self, run_id: str) -> bool:
        """Cancel an in-flight research job (in-process or distributed)."""
        await self.initialize()
        cancelled = False
        task = self._active_tasks.get(run_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            cancelled = True

        if self.run_manager:
            meta = await self.run_manager.get_run_metadata(run_id)
            if not meta:
                return cancelled
            if meta.get("status") in ("planning", "researching", "reviewing", "writing", "queued"):
                if self.queue:
                    await self.queue.request_cancel(run_id)
                await self.run_manager.update_run_status(
                    run_id=run_id,
                    status="cancelled",
                    error_message="Job execution cancelled by caller.",
                )
                await self.broadcaster.broadcast(
                    run_id=run_id,
                    event="job_failed",
                    data={"status": "cancelled", "error": "Job cancelled."},
                )
                cancelled = True
        return cancelled

    async def get_queue_length(self) -> int:
        """Return the count of pending research jobs in the Redis queue."""
        await self.initialize()
        if self.queue:
            return await self.queue.get_queue_length()
        return 0

    async def get_active_workers(self) -> list[dict[str, Any]]:
        """Return active worker nodes with valid heartbeats in Redis."""
        await self.initialize()
        if self.queue:
            return await self.queue.get_active_workers()
        return []


# Global singleton instance
job_service = ResearchJobService()


def get_job_service() -> ResearchJobService:
    """Dependency provider for FastAPI route handlers."""
    return job_service
