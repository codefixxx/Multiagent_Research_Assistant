"""Structured logging setup using structlog with automated secret redaction."""

import logging
import re
import sys
from typing import Any

import structlog

from src.config import settings

# Regex patterns identifying API keys and sensitive tokens across supported providers
SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),  # Google Gemini / Google Cloud
    re.compile(r"sk-(?:proj-)?[a-zA-Z0-9_\-]{20,}"),  # OpenAI
    re.compile(r"sk-ant-[a-zA-Z0-9_\-]{20,}"),  # Anthropic Claude
    re.compile(r"gsk_[a-zA-Z0-9_\-]{20,}"),  # Groq Cloud
    re.compile(r"tvly-[a-zA-Z0-9_\-]{20,}"),  # Tavily Search
    re.compile(r"(Bearer\s+)[A-Za-z0-9_\-=]{20,}", re.IGNORECASE),  # Bearer tokens
]


def redact_secrets_text(text: str) -> str:
    """Scrub sensitive API keys and tokens from text strings."""
    if not text or not isinstance(text, str):
        return text
    for pattern in SECRET_PATTERNS:
        if pattern.groups == 1:
            text = pattern.sub(r"\1[REDACTED_API_KEY]", text)
        else:
            text = pattern.sub("[REDACTED_API_KEY]", text)
    return text


def sanitize_log_value(val: Any) -> Any:
    """Recursively redact secrets from log event dictionaries, lists, and strings."""
    if isinstance(val, str):
        return redact_secrets_text(val)
    if isinstance(val, dict):
        return {k: sanitize_log_value(v) for k, v in val.items()}
    if isinstance(val, list):
        return [sanitize_log_value(v) for v in val]
    if isinstance(val, tuple):
        return tuple(sanitize_log_value(v) for v in val)
    return val


def redact_secrets_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor ensuring secrets are sanitized before rendering or serialization."""
    return sanitize_log_value(event_dict)


class SecretRedactingFilter(logging.Filter):
    """Standard library logging filter redacting secret tokens from standard log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = sanitize_log_value(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(sanitize_log_value(a) for a in record.args)
        return True


def setup_logger():
    """Configure structured logging format for development and production."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        redact_secrets_processor,
    ]

    if settings.ENVIRONMENT == "production":
        processors = shared_processors + [structlog.processors.JSONRenderer()]
    else:
        processors = shared_processors + [structlog.dev.ConsoleRenderer(colors=True)]

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    # Attach secret redacting filter to root logger
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.addFilter(SecretRedactingFilter())


setup_logger()
logger = structlog.get_logger("research_assistant")
