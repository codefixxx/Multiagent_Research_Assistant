"""FastAPI route definitions for research orchestration, status polling, and streaming."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.job_runner import ResearchJobService, get_job_service
from src.api.sse import create_sse_response
from src.schemas.api import (
    AuditTraceResponse,
    ResearchRequest,
    ResearchStatusResponse,
    ResearchSubmissionResponse,
)

router = APIRouter(prefix="/research", tags=["Research"])


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
