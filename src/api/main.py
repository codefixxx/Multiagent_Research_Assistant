"""FastAPI application entrypoint and lifespan management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.api.events import broadcaster
from src.api.job_runner import job_service
from src.api.routes import router as research_router
from src.config import settings
from src.core.exceptions import ApplicationError, classify_error
from src.core.logger import logger
from src.persistence.redis_saver import get_redis_client

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage startup and shutdown lifecycles."""
    logger.info("Initializing Multi-Agent Research Assistant API service...")
    try:
        await job_service.initialize()
        client = await get_redis_client()
        await broadcaster.initialize(client)
        logger.info("Background job service and Redis persistence initialized.")
    except Exception as e:
        logger.warning("Failed during lifespan initialization, fallback will be used", error=str(e))
    yield
    logger.info("Shutting down Multi-Agent Research Assistant API service...")


app = FastAPI(
    title="Multi-Agent Research Assistant API",
    description=(
        "Production-grade multi-agent research service powered by LangGraph, "
        "durable Redis state persistence, pre-flight citation validation, "
        "and real-time Server-Sent Events (SSE) streaming."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# Global Exception Handlers ensuring consistent, structured error responses
@app.exception_handler(ApplicationError)
async def application_error_handler(request: Request, exc: ApplicationError) -> JSONResponse:
    logger.error("Handled ApplicationError", path=request.url.path, code=exc.code, error=exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail_str = str(exc.detail) if exc.detail else "HTTP Error"
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": detail_str,
            "code": f"HTTP_{exc.status_code}",
            "status_code": exc.status_code,
            "suggestion": "Verify your request parameters or URL path.",
            "details": {},
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    app_err = classify_error(exc)
    logger.error("Unhandled exception caught by global handler", path=request.url.path, code=app_err.code, error=app_err.message)
    return JSONResponse(
        status_code=app_err.status_code,
        content=app_err.to_dict(),
    )

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules
app.include_router(research_router)

# Mount static asset directory for the interactive web dashboard
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


@app.get(
    "/dashboard",
    tags=["UI"],
    summary="Interactive Research Dashboard",
    include_in_schema=False,
)
@app.get(
    "/ui",
    tags=["UI"],
    summary="Interactive Research Dashboard (Alias)",
    include_in_schema=False,
)
async def dashboard_view() -> FileResponse:
    """Serve the single-page interactive research workbench."""
    index_path = STATIC_DIR / "index.html"
    return FileResponse(str(index_path))


@app.get(
    "/health",
    tags=["System"],
    summary="Health check and readiness probe",
)
async def health_check() -> dict[str, Any]:
    """Verify system health, persistence layer readiness, and environment settings."""
    redis_healthy = False
    try:
        client = await get_redis_client()
        pong = await client.ping()
        redis_healthy = bool(pong)
    except Exception:
        redis_healthy = False

    active_workers: list[dict[str, Any]] = []
    queue_len = 0
    try:
        active_workers = await job_service.get_active_workers()
        queue_len = await job_service.get_queue_length()
    except Exception:
        pass

    return {
        "status": "healthy",
        "service": "multiagent-research-assistant",
        "version": "0.1.0",
        "redis_connected": redis_healthy,
        "worker_mode": settings.WORKER_MODE,
        "active_workers_count": len(active_workers),
        "active_workers": active_workers,
        "queue_length": queue_len,
        "llm_provider": settings.LLM_PROVIDER,
        "search_engine": settings.SEARCH_ENGINE,
    }


@app.get(
    "/",
    tags=["System"],
    summary="Service landing overview",
)
async def root_overview(request: Request) -> Any:
    """Service description and documentation links."""
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        index_path = STATIC_DIR / "index.html"
        return FileResponse(str(index_path))
    return {
        "title": "Multi-Agent Research Assistant API",
        "status": "operational",
        "dashboard_url": "/dashboard",
        "docs_url": "/docs",
        "openapi_url": "/openapi.json",
        "endpoints": {
            "dashboard": "GET /dashboard",
            "submit_research": "POST /research",
            "poll_status": "GET /research/{run_id}",
            "stream_progress": "GET /research/{run_id}/stream",
            "audit_trace": "GET /research/{run_id}/trace",
            "health": "GET /health",
        },
    }
