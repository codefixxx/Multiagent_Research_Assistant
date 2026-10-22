"""FastAPI route definitions for research orchestration, status polling, and streaming."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from src.api.job_runner import ResearchJobService, get_job_service
from src.api.sse import create_sse_response
from src.core.exceptions import ApplicationError
from src.export import ReportExportEngine
from src.schemas.api import (
    AuditTraceResponse,
    ModelValidationRequest,
    ModelValidationResponse,
    ResearchHistoryItem,
    ResearchHistoryResponse,
    ResearchRequest,
    ResearchStatusResponse,
    ResearchSubmissionResponse,
)

router = APIRouter(prefix="/research", tags=["Research"])


@router.post(
    "/validate-model",
    response_model=ModelValidationResponse,
    summary="Validate LLM model and API key credentials",
    description="Tests credentials and availability of a specific model before launching research.",
)
async def validate_model(
    payload: ModelValidationRequest,
) -> ModelValidationResponse:
    from src.core.llm import verify_model_connectivity

    try:
        res = await verify_model_connectivity(
            provider=payload.provider,
            model_name=payload.model_name,
            api_key=payload.api_key,
        )
        return ModelValidationResponse(
            valid=True,
            provider=res.get("provider", payload.provider or "unknown"),
            model=res.get("model", payload.model_name or "default"),
            message=res.get("message", "Model verified successfully."),
            sample_response=res.get("sample_response"),
        )
    except ApplicationError as exc:
        return ModelValidationResponse(
            valid=False,
            provider=payload.provider or "unknown",
            model=payload.model_name or "default",
            message=exc.message,
            code=exc.code,
            suggestion=exc.suggestion,
        )


@router.post(
    "",
    response_model=ResearchSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a new research job",
    description="Submits a research query and immediately returns a run ID for background processing.",
)
async def submit_research(
    payload: ResearchRequest,
    service: ResearchJobService = Depends(get_job_service),
) -> ResearchSubmissionResponse:
    run_id = str(uuid.uuid4())
    await service.start_job(run_id=run_id, request=payload)
    return ResearchSubmissionResponse(
        run_id=run_id,
        status="queued",
        message="Research job accepted and queued for execution.",
    )


@router.get(
    "/history",
    response_model=ResearchHistoryResponse,
    summary="List recent research runs within retention window",
    description="Retrieves a reverse-chronological list of recent research investigations from Redis cache.",
)
async def list_research_history(
    limit: int = Query(20, ge=1, le=100, description="Max runs to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    service: ResearchJobService = Depends(get_job_service),
) -> ResearchHistoryResponse:
    total, raw_runs = await service.get_history(limit=limit, offset=offset)
    items = []
    for r in raw_runs:
        items.append(
            ResearchHistoryItem(
                run_id=r.get("run_id", ""),
                query=r.get("query", ""),
                status=r.get("status", "planning"),
                focus_mode=r.get("focus_mode", "general"),
                created_at=r.get("created_at"),
                updated_at=r.get("updated_at"),
                step_count=r.get("step_count", 0),
                total_tokens=r.get("total_tokens", 0),
                findings_count=r.get("findings_count", 0),
                cost_summary=r.get("cost_summary"),
                rag_score=r.get("rag_score"),
                has_report=r.get("has_report", False),
                error_message=r.get("error_message"),
                error_code=r.get("error_code"),
                error_suggestion=r.get("error_suggestion"),
            )
        )
    return ResearchHistoryResponse(
        total=total,
        runs=items,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{run_id}",
    response_model=ResearchStatusResponse,
    summary="Get research run status and report",
    description="Polls real-time execution status and retrieves the completed research report when finished.",
)
async def get_research_status(
    run_id: str,
    service: ResearchJobService = Depends(get_job_service),
) -> ResearchStatusResponse:
    status_resp = await service.get_status(run_id)
    if not status_resp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research run '{run_id}' not found.",
        )
    return status_resp


@router.get(
    "/{run_id}/stream",
    summary="Stream live research progress via SSE",
    description="Connect to receive real-time Server-Sent Events detailing agent lifecycle transitions.",
)
async def stream_research_progress(
    run_id: str,
    service: ResearchJobService = Depends(get_job_service),
):
    # Verify that the run exists or was initialized
    status_resp = await service.get_status(run_id)
    if not status_resp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research run '{run_id}' not found.",
        )
    return create_sse_response(run_id=run_id, event_broadcaster=service.broadcaster)


@router.get(
    "/{run_id}/trace",
    response_model=AuditTraceResponse,
    summary="Get step-by-step audit trace",
    description="Retrieves the granular step-by-step execution trace including token metrics and agent hand-offs.",
)
async def get_research_trace(
    run_id: str,
    service: ResearchJobService = Depends(get_job_service),
) -> AuditTraceResponse:
    trace_resp = await service.get_audit_trace(run_id)
    if not trace_resp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit trace for research run '{run_id}' not found.",
        )
    return trace_resp


@router.get(
    "/{run_id}/export",
    summary="Export research report in multiple formats",
    description="Exports the completed research report as PDF, Markdown (.md), Word (.docx), HTML, or JSON.",
)
async def export_research_report(
    run_id: str,
    format: str = Query(
        "pdf",
        description="Desired export format: 'pdf', 'markdown' (or 'md'), 'docx', 'html', or 'json'.",
    ),
    service: ResearchJobService = Depends(get_job_service),
) -> Response:
    status_resp = await service.get_status(run_id)
    if not status_resp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research run '{run_id}' not found.",
        )

    if not status_resp.report and format.lower() not in ("json",):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Research run '{run_id}' does not have a completed report yet (current status: '{status_resp.status}').",
        )

    try:
        content_bytes, media_type, filename = await ReportExportEngine.export(
            status_resp=status_resp,
            format=format,
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        ) from val_err
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate {format.upper()} export: {str(exc)}",
        ) from exc

    return Response(
        content=content_bytes,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post(
    "/{run_id}/cancel",
    summary="Cancel an active research run",
    description="Aborts background execution of an in-flight research job.",
)
async def cancel_research(
    run_id: str,
    service: ResearchJobService = Depends(get_job_service),
) -> dict[str, str]:
    cancelled = await service.cancel_job(run_id)
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Run '{run_id}' is not currently running or cannot be cancelled.",
        )
    return {
        "run_id": run_id,
        "status": "cancelled",
        "message": "Research job successfully cancelled.",
    }
