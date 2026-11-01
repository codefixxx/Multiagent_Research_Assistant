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

# Runtime Stage: Lean Production Image with Playwright Chromium Support
FROM python:3.12-slim AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Security: Create non-root unprivileged service user
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app -s /sbin/nologin appuser

# Install runtime utilities (curl for container healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed site-packages and binaries from builder stage
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Install Playwright Chromium and required OS dependencies for headless scraping
RUN mkdir -p /ms-playwright && \
    playwright install --with-deps chromium && \
    chown -R appuser:appgroup /ms-playwright

# Copy application code with proper ownership
COPY --chown=appuser:appgroup src/ /app/src/
COPY --chown=appuser:appgroup frontend/public/ /app/frontend/public/
COPY --chown=appuser:appgroup --from=frontend-builder /app/frontend/dist/ /app/frontend/dist/
COPY --chown=appuser:appgroup pyproject.toml README.md /app/

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
