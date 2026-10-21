"""Tests verifying Docker Compose stack topology, environment configurations, and Dockerfile healthcheck."""

from pathlib import Path
import yaml
import pytest


def test_dockerfile_exists_and_hardened():
    """Verify Dockerfile exists and enforces security hardening."""
    dockerfile_path = Path("Dockerfile")
    assert dockerfile_path.exists(), "Dockerfile must exist at repository root"
    content = dockerfile_path.read_text(encoding="utf-8")

    assert "FROM python:3.12-slim AS builder" in content
    assert "FROM python:3.12-slim AS runner" in content
    assert "useradd" in content
    assert "USER appuser" in content
    assert "HEALTHCHECK" in content
    assert "playwright install --with-deps chromium" in content


def test_dockerignore_exists_and_excludes_sensitive_artifacts():
    """Verify .dockerignore exists and excludes virtualenvs and credentials."""
    dockerignore_path = Path(".dockerignore")
    assert dockerignore_path.exists(), ".dockerignore must exist"
    content = dockerignore_path.read_text(encoding="utf-8")

    assert ".venv" in content
    assert ".git" in content
    assert "__pycache__" in content
    assert ".env" in content


def test_docker_compose_topology_and_services():
    """Verify docker-compose.yml defines redis, api, and decoupled worker with health checks."""
    compose_path = Path("docker-compose.yml")
    assert compose_path.exists(), "docker-compose.yml must exist"
    
    with open(compose_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    services = config.get("services", {})
    assert "redis" in services, "Redis service must be declared"
    assert "api" in services, "API service must be declared"
    assert "worker" in services, "Dedicated worker service must be declared"

    # Verify Redis healthcheck
    redis_cfg = services["redis"]
    assert "healthcheck" in redis_cfg
    assert redis_cfg["healthcheck"]["test"] == ["CMD", "redis-cli", "ping"]

    # Verify API service configuration
    api_cfg = services["api"]
    assert api_cfg["container_name"] == "research_api"
    assert "8000:8000" in api_cfg["ports"]
    assert api_cfg["depends_on"]["redis"]["condition"] == "service_healthy"

    # Verify decoupled Worker service configuration
    worker_cfg = services["worker"]
    assert worker_cfg["container_name"] == "research_worker"
    assert worker_cfg["command"] == ["python", "-m", "src.worker"]
    assert worker_cfg["depends_on"]["redis"]["condition"] == "service_healthy"

    # Verify environment flags
    worker_env = worker_cfg["environment"]
    worker_env_str = str(worker_env)
    assert "WORKER_MODE=decoupled" in worker_env_str
    assert "PLAYWRIGHT_HEADLESS=true" in worker_env_str
