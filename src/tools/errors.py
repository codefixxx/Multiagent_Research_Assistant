"""Structured error types and status definitions for research and web tools."""

from src.schemas.finding import ExtractionStatus


class ToolError(Exception):
    """Base exception for research tool errors."""

    def __init__(self, message: str, status: ExtractionStatus = ExtractionStatus.ERROR) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class SearchError(ToolError):
    """Raised when search engine queries fail or encounter unrecoverable issues."""


class ScraperError(ToolError):
    """Raised when web page scraping encounters an error."""


def map_http_status_to_extraction_status(status_code: int) -> ExtractionStatus:
    """Map an HTTP response status code to an ExtractionStatus enum."""
    if status_code == 200:
        return ExtractionStatus.SUCCESS
    if status_code in (401, 403):
        return ExtractionStatus.BLOCKED
    if status_code == 402:
        return ExtractionStatus.PAYWALLED
    if status_code == 429:
        return ExtractionStatus.RATE_LIMITED
    if status_code in (408, 504):
        return ExtractionStatus.TIMED_OUT
    return ExtractionStatus.ERROR
