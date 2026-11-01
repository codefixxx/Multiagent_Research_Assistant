# ==============================================================================
# Multi-Agent Research Assistant - Production Dockerfile
# Multi-stage, lean, security-hardened container for FastAPI & LangGraph
# ==============================================================================

# Stage 1: Automated Frontend Production Build
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python Dependency Compilation & Packaging
FROM python:3.12-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
RUN uv pip install --system --no-cache .

# Runtime Stage: Lean Production Image with Playwright Chromium & Redis Support
FROM python:3.12-slim AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/home/appuser \
    PATH=/home/appuser/.local/bin:$PATH

# Security: Create non-root unprivileged service user (UID 1000 required by Hugging Face Spaces)
RUN useradd -m -u 1000 appuser

# Install runtime utilities (curl for healthcheck, redis-server for local state caching)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    redis-server \
    && rm -rf /var/lib/apt/lists/*

# Copy installed site-packages and binaries from builder stage
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Install Playwright Chromium and required OS dependencies for headless scraping
RUN mkdir -p /ms-playwright && \
    playwright install --with-deps chromium && \
    chmod -R 777 /ms-playwright

# Copy application code with proper user ownership
COPY --chown=appuser:appuser src/ /app/src/
COPY --chown=appuser:appuser scripts/ /app/scripts/
COPY --chown=appuser:appuser frontend/public/ /app/frontend/public/
COPY --chown=appuser:appuser --from=frontend-builder /app/frontend/dist/ /app/frontend/dist/
COPY --chown=appuser:appuser pyproject.toml README.md /app/

# Ensure entrypoint script is executable and user owns app/tmp directories
RUN chmod +x /app/scripts/entrypoint.sh && chown -R appuser:appuser /app /tmp

USER appuser

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-7860}/health || exit 1

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
