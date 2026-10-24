"""FastAPI application entrypoint and lifespan management."""

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles

from src.api.events import broadcaster
from src.api.job_runner import job_service
from src.api.routes import router as research_router
from src.config import settings
from src.core.exceptions import ApplicationError, classify_error
from src.core.logger import logger
from src.persistence.redis_saver import get_redis_client

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if not STATIC_DIR.exists():
    _frontend_public = Path(__file__).resolve().parent.parent.parent / "frontend" / "public"
    if _frontend_public.exists():
        STATIC_DIR = _frontend_public


def _get_base_url(request: Request) -> str:
    """Return the authoritative public base URL without trailing slash."""
    if settings.BASE_URL:
        return settings.BASE_URL.rstrip("/")
    return str(request.base_url).rstrip("/")


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
    docs_url=None,
    redoc_url=None,
)


# Global Exception Handlers ensuring consistent, structured error responses
@app.exception_handler(ApplicationError)
async def application_error_handler(request: Request, exc: ApplicationError) -> JSONResponse:
    logger.error(
        "Handled ApplicationError", path=request.url.path, code=exc.code, error=exc.message
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail_str = exc.detail or "HTTP Error"
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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    msg = "; ".join(
        f"{'.'.join(str(loc_part) for loc_part in err.get('loc', []))}: {err.get('msg', '')}"
        for err in errors
    )
    logger.warning("Request validation failed", path=request.url.path, validation_message=msg)
    safe_errors = [
        {
            "loc": [str(x) for x in err.get("loc", [])],
            "msg": str(err.get("msg", "")),
            "type": str(err.get("type", "")),
        }
        for err in errors
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": f"Validation Error: {msg}",
            "code": "VALIDATION_ERROR",
            "status_code": 422,
            "suggestion": "Check input field formats (e.g., API keys must be 10-200 alphanumeric chars without control characters).",
            "details": safe_errors,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    app_err = classify_error(exc)
    logger.error(
        "Unhandled exception caught by global handler",
        path=request.url.path,
        code=app_err.code,
        error=app_err.message,
    )
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


@app.middleware("http")
async def add_security_headers(request: Request, call_next: Callable[[Request], Any]) -> Response:
    """Enforce standard OWASP security headers across all responses."""
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "font-src 'self' data:; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "object-src 'none'; "
        "base-uri 'self';"
    )
    return response

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
async def dashboard_view() -> FileResponse:
    """Serve the single-page interactive research workbench."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        _frontend_index = Path(__file__).resolve().parent.parent.parent / "frontend" / "index.html"
        if _frontend_index.exists():
            index_path = _frontend_index
    return FileResponse(
        str(index_path),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get(
    "/docs",
    tags=["Documentation"],
    summary="Interactive OpenAPI Swagger Documentation",
    include_in_schema=False,
)
async def custom_swagger_ui_html() -> HTMLResponse:
    """Serve self-hosted Swagger UI without inline scripts or external CDNs."""
    html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Multi-Agent Research Assistant API - Swagger UI</title>
    <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
    <link rel="stylesheet" href="/static/docs/swagger-ui.css">
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="/static/docs/swagger-ui-bundle.js"></script>
    <script src="/static/docs/swagger-ui-init.js"></script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get(
    "/redoc",
    tags=["Documentation"],
    summary="Interactive ReDoc Documentation",
    include_in_schema=False,
)
async def custom_redoc_html() -> HTMLResponse:
    """Serve self-hosted ReDoc without inline styles or external CDNs."""
    html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Multi-Agent Research Assistant API - ReDoc</title>
    <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
    <link rel="stylesheet" href="/static/docs/redoc-init.css">
</head>
<body>
    <noscript>ReDoc requires Javascript to function.</noscript>
    <redoc spec-url="/openapi.json"></redoc>
    <script src="/static/docs/redoc.standalone.js"></script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get(
    "/ui",
    tags=["UI"],
    summary="Interactive Research Dashboard (Canonical Redirect)",
    include_in_schema=False,
)
async def ui_redirect() -> RedirectResponse:
    """Canonical 301 redirect to consolidate indexing authority to /dashboard."""
    return RedirectResponse(url="/dashboard", status_code=301)


@app.get(
    "/favicon.ico",
    include_in_schema=False,
)
@app.get(
    "/favicon.svg",
    include_in_schema=False,
)
async def favicon_view() -> FileResponse:
    """Serve the official SVG brand favicon."""
    favicon_path = STATIC_DIR / "favicon.svg"
    return FileResponse(str(favicon_path), media_type="image/svg+xml")


@app.get(
    "/robots.txt",
    tags=["SEO"],
    summary="Search Engine Crawling Directives",
    include_in_schema=False,
    response_class=PlainTextResponse,
)
async def robots_txt(request: Request) -> PlainTextResponse:
    """Provide crawl instructions for search engine bots."""
    base_url = _get_base_url(request)
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /dashboard\n"
        "Disallow: /research/\n"
        "Disallow: /api/\n"
        "Disallow: /docs\n"
        "Disallow: /redoc\n"
        "Disallow: /openapi.json\n\n"
        f"Sitemap: {base_url}/sitemap.xml\n"
    )
    return PlainTextResponse(content=content, media_type="text/plain; charset=utf-8")


@app.get(
    "/sitemap.xml",
    tags=["SEO"],
    summary="XML Sitemap for Search Engine Discovery",
    include_in_schema=False,
    response_class=Response,
)
async def sitemap_xml(request: Request) -> Response:
    """Provide XML sitemap listing indexable public application routes."""
    base_url = _get_base_url(request)
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "  <url>\n"
        f"    <loc>{base_url}/dashboard</loc>\n"
        "    <changefreq>weekly</changefreq>\n"
        "    <priority>1.0</priority>\n"
        "  </url>\n"
        "</urlset>\n"
    )
    return Response(content=content, media_type="application/xml; charset=utf-8")


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
        "require_byok": settings.REQUIRE_BYOK,
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
        return RedirectResponse(url="/dashboard", status_code=307)
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
