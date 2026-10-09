"""FastAPI production service package for the Multi-Agent Research Assistant."""

from src.api.job_runner import ResearchJobService, get_job_service
from src.api.main import app

__all__ = ["app", "ResearchJobService", "get_job_service"]
