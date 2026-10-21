"""Structured application exception hierarchy and intelligent error classification.

Provides typed exceptions, error codes, actionable remediation suggestions,
and error classification across LLM providers (Gemini, Groq, OpenAI, Anthropic),
search/scraping tools, and workflow execution.
"""

from datetime import UTC, datetime
from typing import Any


class ApplicationError(Exception):
    """Base exception for all application errors across the multi-agent research assistant."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        suggestion: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.suggestion = suggestion or "Please verify your configuration or check server logs."
        self.details = details or {}
        self.timestamp = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Convert exception details to a serializable dictionary."""
        return {
            "error": self.message,
            "code": self.code,
            "status_code": self.status_code,
            "suggestion": self.suggestion,
            "details": self.details,
            "timestamp": self.timestamp,
        }


class ConfigurationError(ApplicationError):
    """Raised when configuration, credentials, or environment variables are invalid."""

    def __init__(
        self,
        message: str,
        code: str = "CONFIG_ERROR",
        status_code: int = 400,
        suggestion: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            suggestion=suggestion or "Verify your environment variables in .env or Settings.",
            details=details,
        )


class LLMConfigurationError(ConfigurationError):
    """Raised when LLM credentials or configuration are invalid."""

    def __init__(
        self,
        message: str,
        code: str = "LLM_CONFIG_ERROR",
        status_code: int = 400,
        suggestion: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            suggestion=suggestion or "Configure the required API key in .env or the Settings dialog.",
            details=details,
        )


class ModelError(ApplicationError):
    """Base exception for errors originating from LLM interactions."""

    def __init__(
        self,
        message: str,
        code: str = "MODEL_ERROR",
        status_code: int = 502,
        suggestion: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            suggestion=suggestion or "Check the model configuration or try switching to another provider.",
            details=details,
        )


class AuthenticationError(ModelError):
    """Raised when LLM provider authentication fails (invalid/missing API key, 401/403)."""

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        code: str = "INVALID_API_KEY",
        status_code: int = 401,
        suggestion: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        prov_name = (provider or "the model provider").capitalize()
        sugg = suggestion or f"Please verify and update your {prov_name} API key in Settings or .env file."
        d = dict(details or {})
        if provider:
            d["provider"] = provider
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            suggestion=sugg,
            details=d,
        )


class InvalidModelError(ModelError):
    """Raised when an unrecognized, nonexistent, or unsupported model name is requested."""

    def __init__(
        self,
        message: str,
        model_name: str | None = None,
        provider: str | None = None,
        code: str = "MODEL_NOT_FOUND",
        status_code: int = 400,
        suggestion: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        d = dict(details or {})
        if model_name:
            d["model_name"] = model_name
        if provider:
            d["provider"] = provider
        sugg = (
            suggestion
            or f"Check the model name '{model_name or ''}'. Verify that it is available and enabled on your account."
        )
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            suggestion=sugg,
            details=d,
        )


class RateLimitError(ModelError):
    """Raised when LLM provider rate limits or quotas are exceeded (429, RESOURCE_EXHAUSTED)."""

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        code: str = "RATE_LIMIT_EXCEEDED",
        status_code: int = 429,
        suggestion: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        prov_name = (provider or "the model provider").capitalize()
        sugg = (
            suggestion
            or f"Rate limit or token quota reached for {prov_name}. Wait a moment before retrying or check your quota balance."
        )
        d = dict(details or {})
        if provider:
            d["provider"] = provider
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            suggestion=sugg,
            details=d,
        )


class ModelProviderError(ModelError):
    """Raised when an LLM provider is down, overloaded, or throws 500/502/503/504/timeout."""

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        code: str = "PROVIDER_UNAVAILABLE",
        status_code: int = 502,
        suggestion: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        prov_name = (provider or "the model provider").capitalize()
        sugg = (
            suggestion
            or f"{prov_name} service is currently unavailable or experiencing high latency. Try again shortly or switch providers."
        )
        d = dict(details or {})
        if provider:
            d["provider"] = provider
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            suggestion=sugg,
            details=d,
        )


class ToolExecutionError(ApplicationError):
    """Raised when search or scraping tools encounter unrecoverable errors."""

    def __init__(
        self,
        message: str,
        tool_name: str | None = None,
        code: str = "TOOL_ERROR",
        status_code: int = 502,
        suggestion: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        d = dict(details or {})
        if tool_name:
            d["tool_name"] = tool_name
        sugg = suggestion or "Verify network access and tool API keys (e.g. Tavily, Jina Reader)."
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            suggestion=sugg,
            details=d,
        )


class PipelineExecutionError(ApplicationError):
    """Raised when a LangGraph node or state machine execution fails."""

    def __init__(
        self,
        message: str,
        node: str | None = None,
        code: str = "PIPELINE_ERROR",
        status_code: int = 500,
        suggestion: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        d = dict(details or {})
        if node:
            d["node"] = node
        sugg = suggestion or "Check server execution logs for details on the failing agent node."
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            suggestion=sugg,
            details=d,
        )


def classify_error(
    exc: Exception,
    provider: str | None = None,
    model_name: str | None = None,
    node: str | None = None,
) -> ApplicationError:
    """Classify any exception (LLM SDK, network, tool, runtime) into a typed ApplicationError.

    Extracts error codes, status codes, and generates crisp, actionable remediation advice.
    """
    if type(exc).__name__ == "CrashTriggerError":
        raise exc

    if isinstance(exc, ApplicationError):
        if provider and "provider" not in exc.details:
            exc.details["provider"] = provider
        if model_name and "model_name" not in exc.details:
            exc.details["model_name"] = model_name
        if node and "node" not in exc.details:
            exc.details["node"] = node
        return exc

    err_str = str(exc)
    err_lower = err_str.lower()
    exc_type_name = type(exc).__name__

    # Infer provider if not supplied
    inferred_provider = provider
    if not inferred_provider and model_name:
        m = model_name.lower().strip()
        if "gemini" in m:
            inferred_provider = "gemini"
        elif "gpt" in m or "o1" in m or "o3" in m or "openai" in m:
            inferred_provider = "openai"
        elif "claude" in m or "anthropic" in m:
            inferred_provider = "anthropic"
        elif any(k in m for k in ("llama", "mixtral", "gemma", "qwen", "groq")):
            inferred_provider = "groq"
        elif "ollama" in m:
            inferred_provider = "ollama"
        elif "mock" in m:
            inferred_provider = "mock"

    inferred_provider = inferred_provider or "model provider"
    prov_title = inferred_provider.capitalize()

    # 1. Authentication / API Key failure
    auth_indicators = [
        "api_key_invalid",
        "invalid api key",
        "api key not valid",
        "incorrect api key",
        "invalid x-api-key",
        "unauthenticated",
        "unauthorized",
        "permission_denied",
        "permissiondenied",
        "the caller does not have permission",
        "forbidden",
        "401",
        "403",
    ]
    if any(ind in err_lower for ind in auth_indicators) or any(
        t in exc_type_name for t in ("AuthenticationError", "Unauthenticated", "PermissionDenied")
    ):
        return AuthenticationError(
            message=f"Authentication failed for {prov_title}: Invalid or unauthorized API key.",
            provider=inferred_provider,
            code="INVALID_API_KEY",
            suggestion=f"Please verify and configure a valid {prov_title} API key in Settings or .env file.",
            details={"original_error": err_str, "exception_type": exc_type_name, "model": model_name},
        )

    # 2. Non-existent or unsupported Model Name
    not_found_indicators = [
        "is not found for api version",
        "model not found",
        "model_not_found",
        "does not exist",
        "is not supported for generatecontent",
        "not_found_error",
        "call listmodels",
        "404",
        "unsupported llm provider",
    ]
    if any(ind in err_lower for ind in not_found_indicators) or any(
        t in exc_type_name for t in ("NotFoundError", "NotFound")
    ):
        m_display = model_name or "selected model"
        if inferred_provider == "gemini":
            sugg = f"Model '{m_display}' was not found. Recommended Gemini models: 'gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-1.5-flash'."
        elif inferred_provider == "groq":
            sugg = f"Model '{m_display}' was not found. Recommended Groq models: 'llama-3.3-70b-versatile', 'llama3-70b-8192', 'mixtral-8x7b-32768'."
        elif inferred_provider == "openai":
            sugg = f"Model '{m_display}' was not found. Recommended OpenAI models: 'gpt-4o', 'gpt-4o-mini', 'o3-mini'."
        elif inferred_provider == "anthropic":
            sugg = f"Model '{m_display}' was not found. Recommended Anthropic models: 'claude-3-5-sonnet-20241022', 'claude-3-haiku-20240307'."
        else:
            sugg = f"Verify the spelling of '{m_display}' and ensure it is supported by {prov_title}."

        return InvalidModelError(
            message=f"The chosen model '{m_display}' was not found or is not supported by {prov_title}.",
            model_name=model_name,
            provider=inferred_provider,
            code="MODEL_NOT_FOUND",
            suggestion=sugg,
            details={"original_error": err_str, "exception_type": exc_type_name},
        )

    # 3. Rate Limit / Quota Exceeded
    rate_limit_indicators = [
        "rate limit",
        "quota",
        "resource_exhausted",
        "resourceexhausted",
        "429",
        "too many requests",
        "tokens per minute",
        "requests per minute",
    ]
    if any(ind in err_lower for ind in rate_limit_indicators) or any(
        t in exc_type_name for t in ("RateLimitError", "ResourceExhausted")
    ):
        return RateLimitError(
            message=f"Rate limit or quota exceeded for {prov_title}.",
            provider=inferred_provider,
            code="RATE_LIMIT_EXCEEDED",
            suggestion=f"You have reached your request rate limit or token quota on {prov_title}. Please wait a moment before retrying or check your quota balance.",
            details={"original_error": err_str, "exception_type": exc_type_name, "model": model_name},
        )

    # 4. Service Unavailable / Outage / Server Errors (5xx, timeouts)
    down_indicators = [
        "service unavailable",
        "503",
        "502",
        "500",
        "internal server error",
        "bad gateway",
        "overloaded",
        "apiconnectionerror",
        "connection error",
        "server disconnected",
        "timed out",
        "timeout",
    ]
    if any(ind in err_lower for ind in down_indicators) or any(
        t in exc_type_name
        for t in ("ServiceUnavailable", "InternalServerError", "APIConnectionError", "TimeoutError")
    ):
        return ModelProviderError(
            message=f"{prov_title} service is currently unavailable or encountered an internal error.",
            provider=inferred_provider,
            code="PROVIDER_UNAVAILABLE",
            suggestion=f"{prov_title} servers might be experiencing heavy load or downtime. Please try again shortly or switch to a different model.",
            details={"original_error": err_str, "exception_type": exc_type_name, "model": model_name},
        )

    # 5. Tool / Scraper / Search failure
    if any(t in exc_type_name.lower() for t in ("tool", "search", "scraper", "httpx")):
        return ToolExecutionError(
            message=f"Research tool execution failed: {err_str}",
            tool_name=node or "research_tool",
            code="TOOL_ERROR",
            suggestion="Verify web search engine connectivity (Tavily/DuckDuckGo) and internet connection.",
            details={"original_error": err_str, "exception_type": exc_type_name},
        )

    # 6. Fallback general pipeline error
    return PipelineExecutionError(
        message=f"Pipeline execution error: {err_str}",
        node=node,
        code="PIPELINE_ERROR",
        suggestion="An unexpected error occurred during execution. Please check application logs for details.",
        details={"original_error": err_str, "exception_type": exc_type_name, "model": model_name, "provider": provider},
    )
