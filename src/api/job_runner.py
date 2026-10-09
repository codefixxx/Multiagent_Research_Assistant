"""Background job execution engine for the multi-agent research workflow."""

import asyncio
import time
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

from src.api.events import EventBroadcaster, broadcaster
from src.core.logger import logger
from src.core.telemetry import TokenUsage
from src.graph.builder import _normalize_tokens, compile_research_graph, create_initial_state
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
    validate_report_citations,
)


class ResearchJobService:
    """Manages background research runs, LangGraph execution, and state persistence."""

    def __init__(
        self,
        run_manager: RedisRunManager | None = None,
        event_broadcaster: EventBroadcaster | None = None,
        idempotency_cache: NodeIdempotencyCache | None = None,
        checkpointer: Any = None,
        llm: BaseChatModel | None = None,
    ) -> None:
        self.run_manager = run_manager
        self.broadcaster = event_broadcaster or broadcaster
        self.idempotency_cache = idempotency_cache
        self.checkpointer = checkpointer
        self.default_llm = llm
        self._active_tasks: dict[str, asyncio.Task[Any]] = {}

    async def initialize(self) -> None:
        """Initialize Redis connection and dependencies if not already supplied."""
        if self.run_manager is None:
            client = await get_redis_client()
            self.run_manager = RedisRunManager(client)
            self.idempotency_cache = NodeIdempotencyCache(client)
            self.checkpointer = await get_checkpointer(client)

    async def start_job(
        self,
        run_id: str,
        request: ResearchRequest,
        llm_override: BaseChatModel | None = None,
    ) -> None:
        """Schedule and launch a research job in a detached background asyncio task."""
        if not self.run_manager:
            await self.initialize()

        assert self.run_manager is not None
        # Initialize run metadata in Redis
        await self.run_manager.init_run(run_id=run_id, query=request.query)

        # Notify subscribers that job has been queued
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

        # Compile the graph bound to this run's persistence checkpointer
        graph = compile_research_graph(
            llm=llm,
            checkpointer=self.checkpointer,
            run_manager=self.run_manager,
            idempotency_cache=self.idempotency_cache,
        )

        initial_state = create_initial_state(query=request.query, run_id=run_id)
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

        try:
            async for chunk in graph.astream(initial_state, config=config, stream_mode="updates"):
                for node_name, node_output in chunk.items():
                    merged_state.update(node_output)

                    # Dispatch event based on which agent just finished
                    if node_name == "planner":
                        plan = node_output.get("plan")
                        sub_questions_count = len(plan.sub_questions) if plan else 0
                        await self.broadcaster.broadcast(
                            run_id=run_id,
                            event="planner_completed",
                            data={
                                "node": "planner",
                                "status": "researching",
                                "sub_questions_count": sub_questions_count,
                                "objective": getattr(plan, "objective", ""),
                            },
                        )

                    elif node_name == "researcher":
                        findings = node_output.get("findings", [])
                        new_findings = node_output.get("current_sub_question_findings", [])
                        await self.broadcaster.broadcast(
                            run_id=run_id,
                            event="researching_subquestion",
                            data={
                                "node": "researcher",
                                "status": "reviewing",
                                "new_findings_count": len(new_findings),
                                "total_findings_count": len(findings),
                            },
                        )

                    elif node_name == "reviewer":
                        is_revision = bool(node_output.get("review_feedback"))
                        next_idx = node_output.get("current_sub_question_index", 0)
                        await self.broadcaster.broadcast(
                            run_id=run_id,
                            event="subquestion_reviewed",
                            data={
                                "node": "reviewer",
                                "is_revision": is_revision,
                                "next_sub_question_index": next_idx,
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

            # Execution completed
            final_status = merged_state.get("status", "completed")
            raw_report = merged_state.get("report")
            findings_list = merged_state.get("findings", [])

            # Run Pre-flight Citation Validation
            citation_validation: CitationValidationResult | None = None
            final_report: ResearchReport | None = None
            if raw_report and isinstance(raw_report, ResearchReport):
                findings_obj_list = [
                    f if isinstance(f, FindingRecord) else FindingRecord.model_validate(f)
                    for f in findings_list
                ]
                citation_validation = validate_report_citations(
                    report=raw_report,
                    findings=findings_obj_list,
                    auto_sanitize=True,
                )
                final_report = citation_validation.sanitized_report
            elif isinstance(raw_report, dict):
                final_report = ResearchReport.model_validate(raw_report)

            # Persist Report in Redis
            if final_report is not None:
                report_dict: dict[str, Any] = final_report.model_dump(mode="json")
                await self.run_manager.save_report(run_id=run_id, report_data=report_dict)

            # Assemble & Persist Audit Log
            raw_traces = merged_state.get("audit_traces", [])
            step_traces = [
                t if isinstance(t, StepTrace) else StepTrace.model_validate(t) for t in raw_traces
            ]
            total_tokens = _normalize_tokens(merged_state.get("total_tokens"))
            total_latency = (time.time() - start_time) * 1000.0

            audit_log = AuditLog(
                run_id=run_id,
                query=request.query,
                steps=step_traces,
                total_token_usage=total_tokens,
                total_latency_ms=total_latency,
                status=final_status,
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
            )

            # Broadcast final completion event
            await self.broadcaster.broadcast(
                run_id=run_id,
                event="job_completed" if final_status == "completed" else "budget_exceeded",
                data={
                    "status": final_status,
                    "title": final_report.title if final_report else "",
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
                },
            )
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
            await self.broadcaster.broadcast(
                run_id=run_id,
                event="job_failed",
                data={"status": "cancelled", "error": "Job cancelled."},
            )
            raise

        except Exception as e:
            logger.error(
                "Research job execution failed with exception", run_id=run_id, error=str(e)
            )
            await self.run_manager.update_run_status(
                run_id=run_id,
                status="failed",
                error_message=str(e),
            )
            await self.broadcaster.broadcast(
                run_id=run_id,
                event="job_failed",
                data={"status": "failed", "error": str(e)},
            )

    async def get_status(self, run_id: str) -> ResearchStatusResponse | None:
        """Fetch current status and report (if completed) for a given run ID."""
        if not self.run_manager:
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

        return ResearchStatusResponse(
            run_id=run_id,
            query=meta.get("query", ""),
            status=status,
            progress_pct=progress_pct,
            current_node=current_node,
            step_count=meta.get("step_count", 0),
            total_tokens=meta.get("total_tokens", 0),
            findings_count=0,
            report=report_obj,
            error_message=meta.get("error_message"),
            created_at=meta.get("created_at"),
            updated_at=meta.get("updated_at"),
        )

    async def get_audit_trace(self, run_id: str) -> AuditTraceResponse | None:
        """Retrieve the complete audit trail and step-by-step metrics for a run."""
        if not self.run_manager:
            await self.initialize()
        assert self.run_manager is not None

        raw_audit = await self.run_manager.get_audit_log(run_id)
        if raw_audit:
            audit = AuditLog.model_validate(raw_audit)
            return AuditTraceResponse(
                run_id=run_id,
                query=audit.query,
                status=audit.status,
                total_latency_ms=audit.total_latency_ms,
                total_tokens=audit.total_token_usage,
                step_count=len(audit.steps),
                steps=audit.steps,
                error=audit.error,
            )

        # Fallback to metadata if audit log is not yet written
        meta = await self.run_manager.get_run_metadata(run_id)
        if not meta:
            return None

        return AuditTraceResponse(
            run_id=run_id,
            query=meta.get("query", ""),
            status=meta.get("status", "planning"),
            total_latency_ms=0.0,
            total_tokens=TokenUsage(total_tokens=meta.get("total_tokens", 0)),
            step_count=meta.get("step_count", 0),
            steps=[],
            error=meta.get("error_message"),
        )

    async def cancel_job(self, run_id: str) -> bool:
        """Cancel an in-flight research job if currently running."""
        task = self._active_tasks.get(run_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            if self.run_manager:
                await self.run_manager.update_run_status(
                    run_id=run_id,
                    status="cancelled",
                    error_message="Job execution cancelled by caller.",
                )
            return True
        return False


# Global singleton instance
job_service = ResearchJobService()


def get_job_service() -> ResearchJobService:
    """Dependency provider for FastAPI route handlers."""
    return job_service
