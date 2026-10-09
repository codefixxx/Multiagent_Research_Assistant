"""FastAPI application entrypoint and lifespan management."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.job_runner import job_service
from src.api.routes import router as research_router
from src.config import settings
from src.core.logger import logger
from src.persistence.redis_saver import get_redis_client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown lifecycles."""
    logger.info("Initializing Multi-Agent Research Assistant API service...")
    try:
        await job_service.initialize()
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

    return {
        "status": "healthy",
        "service": "multiagent-research-assistant",
        "version": "0.1.0",
        "redis_connected": redis_healthy,
        "llm_provider": settings.LLM_PROVIDER,
        "search_engine": settings.SEARCH_ENGINE,
    }


@app.get(
    "/",
    tags=["System"],
    summary="Service landing overview",
)
async def root_overview() -> dict[str, Any]:
    """Service description and documentation links."""
    return {
        "title": "Multi-Agent Research Assistant API",
        "status": "operational",
        "docs_url": "/docs",
        "openapi_url": "/openapi.json",
        "endpoints": {
            "submit_research": "POST /research",
            "poll_status": "GET /research/{run_id}",
            "stream_progress": "GET /research/{run_id}/stream",
            "audit_trace": "GET /research/{run_id}/trace",
            "health": "GET /health",
        },
    }
