"""Server-Sent Events (SSE) streaming utilities."""

from fastapi.responses import StreamingResponse

from src.api.events import EventBroadcaster, broadcaster


def create_sse_response(
    run_id: str,
    event_broadcaster: EventBroadcaster | None = None,
) -> StreamingResponse:
    """Create a StreamingResponse for Server-Sent Events (SSE).

    Ensures proper HTTP streaming headers to prevent proxy buffering.
    """
    b = event_broadcaster or broadcaster

    return StreamingResponse(
        b.subscribe(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
            "X-Accel-Buffering": "no",
        },
    )
