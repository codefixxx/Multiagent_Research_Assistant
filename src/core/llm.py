"""Provider-Agnostic LLM Factory with support for Groq, Gemini, and Mock models."""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from pydantic import SecretStr

from src.config import settings
from src.core.exceptions import (
    AuthenticationError,
    InvalidModelError,
    LLMConfigurationError,
    classify_error,
)
from src.core.logger import logger
from src.core.telemetry import TokenUsage


def detect_provider(model_name: str | None, default_provider: str | None = None) -> str:
    """Infer the LLM provider based on model naming conventions."""
    if not model_name:
        return (default_provider or settings.LLM_PROVIDER).lower()
    m = model_name.lower().strip()
    if m.startswith("gemini") or "models/gemini" in m:
        return "gemini"
    if m.startswith("gpt-") or m.startswith("o1") or m.startswith("o3") or "openai" in m:
        return "openai"
    if m.startswith("claude") or "anthropic" in m:
        return "anthropic"
    if (
        m.startswith("llama")
        or m.startswith("mixtral")
        or m.startswith("gemma")
        or m.startswith("qwen")
        or "groq" in m
    ):
        return "groq"
    if "ollama" in m:
        return "ollama"
    if m == "mock":
        return "mock"
    return (default_provider or settings.LLM_PROVIDER).lower()


def resolve_api_key(raw_key: str | None, provider: str) -> str | None:
    """Resolve API key based on BYOK client input and REQUIRE_BYOK settings."""
    if raw_key:
        return raw_key
    if settings.REQUIRE_BYOK:
        return None
    # Local/development fallback to server .env
    env_keys = {
        "gemini": settings.GEMINI_API_KEY,
        "groq": settings.GROQ_API_KEY,
        "openai": settings.OPENAI_API_KEY,
        "anthropic": settings.ANTHROPIC_API_KEY,
    }
    return env_keys.get(provider.lower())


def validate_model_configuration(
    provider: str | None = None,
    model_name: str | None = None,
    api_key: str | SecretStr | None = None,
) -> None:
    """Validate provider, model selection, and key presence without initiating external network calls."""
    raw_key = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
    target_provider = (provider or detect_provider(model_name)).lower()
    valid_providers = {"gemini", "groq", "openai", "anthropic", "ollama", "mock"}
    if target_provider not in valid_providers:
        raise InvalidModelError(
            f"Unsupported LLM provider: '{target_provider}'. Supported: {', '.join(sorted(valid_providers))}.",
            model_name=model_name,
            provider=target_provider,
            suggestion=f"Please specify a supported provider from: {', '.join(sorted(valid_providers))}.",
        )

    # Check key requirements
    if target_provider in {"gemini", "groq", "openai", "anthropic"}:
        active_key = resolve_api_key(raw_key, target_provider)
        if not active_key:
            provider_title = target_provider.title()
            if settings.REQUIRE_BYOK:
                msg = f"Bring Your Own Key required: No API key provided for '{target_provider}'."
                suggestion = f"Please provide your {provider_title} API key in Settings before launching research."
                code = "BYOK_REQUIRED"
            else:
                msg = f"{target_provider.upper()}_API_KEY is not configured."
                suggestion = (
                    f"Please provide a {provider_title} API key in Settings or set "
                    f"{target_provider.upper()}_API_KEY in .env."
                )
                code = "INVALID_API_KEY"
            raise AuthenticationError(
                msg, provider=target_provider, code=code, suggestion=suggestion
            )


async def verify_model_connectivity(
    provider: str | None = None,
    model_name: str | None = None,
    api_key: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    """Test connection to the specified LLM to verify credentials and model availability.

    Returns a dict on success or raises classified ApplicationError (e.g. AuthenticationError, InvalidModelError).
    """
    import asyncio

    from langchain_core.messages import HumanMessage

    validate_model_configuration(provider=provider, model_name=model_name, api_key=api_key)
    target_provider = (provider or detect_provider(model_name)).lower()
    chat_model = get_chat_model(
        provider=target_provider,
        model_name=model_name,
        api_key=api_key,
        temperature=0.0,
        max_tokens=10,
    )

    test_message = [HumanMessage(content="Respond with 'OK'.")]
    try:
        response = await asyncio.wait_for(
            chat_model.ainvoke(test_message),
            timeout=timeout_seconds,
        )
        content = getattr(response, "content", "OK")
        resolved_name = (
            model_name
            or getattr(chat_model, "model_name", None)
            or getattr(chat_model, "model", None)
            or target_provider
        )
        return {
            "valid": True,
            "provider": target_provider,
            "model": str(resolved_name),
            "message": "Model connection and authentication verified successfully.",
            "sample_response": str(content)[:50],
        }
    except Exception as exc:
        classified = classify_error(
            exc,
            provider=target_provider,
            model_name=model_name,
            node="model_verifier",
        )
        logger.warning(
            "Model connectivity test failed",
            provider=target_provider,
            model=model_name,
            code=classified.code,
            error=classified.message,
        )
        raise classified from exc


def get_chat_model(
    provider: str | None = None,
    model_name: str | None = None,
    api_key: str | SecretStr | None = None,
    temperature: float = 0.1,
    max_tokens: int | None = None,
) -> BaseChatModel:
    """Instantiate and return a configured BaseChatModel based on settings and available keys.

    Supports:
        - "gemini": Google Gemini models (Gemini 2.5 Flash, 3.5 Flash Lite, etc.).
        - "openai": OpenAI GPT models (GPT-4o, GPT-4o-mini, etc.).
        - "anthropic": Anthropic Claude models (Claude 3.5 Sonnet, Haiku, etc.).
        - "groq": Fast open-source inference with Llama 3.3 70B.
        - "ollama": Local inference models via Ollama.
        - "mock": Mock chat model for testing without API keys.
    """
    raw_key = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
    target_provider = (provider or detect_provider(model_name)).lower()

    if target_provider == "gemini":
        active_key = resolve_api_key(raw_key, "gemini")
        if not active_key:
            if settings.REQUIRE_BYOK:
                raise AuthenticationError(
                    "Bring Your Own Key required: No API key provided for 'gemini'.",
                    provider="gemini",
                    code="BYOK_REQUIRED",
                    suggestion="Please provide your Gemini API key in Settings before launching research.",
                )
            raise AuthenticationError(
                "GEMINI_API_KEY is not configured.",
                provider="gemini",
                suggestion="Please provide a Gemini API key in Settings or set GEMINI_API_KEY in .env.",
            )
        active_model = model_name or settings.LLM_MODEL or settings.GEMINI_MODEL
        if active_model.startswith("models/"):
            active_model = active_model.replace("models/", "")
        logger.info("Initializing Gemini Chat Model", provider="gemini", model=active_model)
        return ChatGoogleGenerativeAI(
            google_api_key=active_key,
            model=active_model,
            temperature=temperature,
            max_output_tokens=max_tokens,
            timeout=60.0,
            max_retries=3,
        )

    if target_provider == "openai":
        active_key = resolve_api_key(raw_key, "openai")
        if not active_key:
            if settings.REQUIRE_BYOK:
                raise AuthenticationError(
                    "Bring Your Own Key required: No API key provided for 'openai'.",
                    provider="openai",
                    code="BYOK_REQUIRED",
                    suggestion="Please provide your OpenAI API key in Settings before launching research.",
                )
            raise LLMConfigurationError(
                "OPENAI_API_KEY is not configured. "
                "Please provide an API key in Settings or set OPENAI_API_KEY in .env."
            )
        active_model = model_name or settings.OPENAI_MODEL
        logger.info("Initializing OpenAI Chat Model", provider="openai", model=active_model)
        from langchain_openai import ChatOpenAI

        openai_kwargs: dict[str, Any] = {}
        if max_tokens is not None:
            openai_kwargs["max_tokens"] = max_tokens

        return ChatOpenAI(
            api_key=SecretStr(active_key),
            model=active_model,
            temperature=temperature,
            **openai_kwargs,
        )

    if target_provider == "anthropic":
        active_key = resolve_api_key(raw_key, "anthropic")
        if not active_key:
            if settings.REQUIRE_BYOK:
                raise AuthenticationError(
                    "Bring Your Own Key required: No API key provided for 'anthropic'.",
                    provider="anthropic",
                    code="BYOK_REQUIRED",
                    suggestion="Please provide your Anthropic API key in Settings before launching research.",
                )
            raise LLMConfigurationError(
                "ANTHROPIC_API_KEY is not configured. "
                "Please provide an API key in Settings or set ANTHROPIC_API_KEY in .env."
            )
        active_model = model_name or settings.ANTHROPIC_MODEL
        logger.info("Initializing Anthropic Chat Model", provider="anthropic", model=active_model)
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            api_key=SecretStr(active_key),
            model_name=active_model,
            temperature=temperature,
            max_tokens_to_sample=max_tokens or 4096,
            timeout=None,
            stop=None,
        )

    if target_provider == "groq":
        active_key = resolve_api_key(raw_key, "groq")
        if not active_key:
            if settings.REQUIRE_BYOK:
                raise AuthenticationError(
                    "Bring Your Own Key required: No API key provided for 'groq'.",
                    provider="groq",
                    code="BYOK_REQUIRED",
                    suggestion="Please provide your Groq API key in Settings before launching research.",
                )
            if settings.GEMINI_API_KEY:
                logger.warning(
                    "GROQ_API_KEY not found; falling back to Gemini provider",
                    requested=target_provider,
                    fallback="gemini",
                )
                return get_chat_model(
                    provider="gemini",
                    model_name=model_name,
                    api_key=raw_key,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            raise LLMConfigurationError(
                "GROQ_API_KEY is not configured in .env or environment variables. "
                "Please set GROQ_API_KEY or switch LLM_PROVIDER to gemini/mock."
            )
        active_model = model_name or settings.LLM_MODEL or settings.GROQ_MODEL
        logger.info("Initializing Groq Chat Model", provider="groq", model=active_model)
        return ChatGroq(
            api_key=SecretStr(active_key),
            model=active_model,
            temperature=temperature,
            max_tokens=max_tokens or 4096,
        )

    if target_provider == "ollama":
        active_model = model_name or settings.OLLAMA_MODEL
        logger.info("Initializing Ollama Chat Model", provider="ollama", model=active_model)
        try:
            import importlib

            ollama_mod = importlib.import_module("langchain_community.chat_models")
            chat_ollama_cls = getattr(ollama_mod, "ChatOllama")
            return chat_ollama_cls(
                base_url=settings.OLLAMA_BASE_URL,
                model=active_model,
                temperature=temperature,
            )
        except (ImportError, AttributeError):
            raise LLMConfigurationError(
                "langchain-community is required for Ollama provider. Please install it."
            )

    if target_provider == "mock":
        from tests.conftest import MockChatModel

        logger.debug("Initializing Mock Chat Model")
        return MockChatModel()

    raise LLMConfigurationError(
        f"Unsupported LLM provider: '{target_provider}'. Supported: gemini, openai, anthropic, groq, ollama, mock."
    )


def extract_token_usage(response: Any) -> TokenUsage:
    """Extract prompt and completion token counts from an LLM response object."""
    usage = TokenUsage()
    if isinstance(response, AIMessage):
        metadata = getattr(response, "response_metadata", {}) or {}
        # Format 1: Groq usage metadata
        token_usage_dict = metadata.get("token_usage", {})
        if token_usage_dict:
            prompt = token_usage_dict.get("prompt_tokens", 0)
            completion = token_usage_dict.get("completion_tokens", 0)
            usage.add(prompt, completion)
            return usage

        # Format 2: Google GenAI usage metadata
        genai_usage = metadata.get("usage_metadata", {})
        if genai_usage:
            prompt = genai_usage.get("prompt_token_count", 0)
            completion = genai_usage.get("candidates_token_count", 0)
            usage.add(prompt, completion)
            return usage

        # Format 3: LangChain standard usage_metadata attribute on AIMessage
        std_usage = getattr(response, "usage_metadata", None)
        if std_usage and isinstance(std_usage, dict):
            prompt = std_usage.get("input_tokens", 0)
            completion = std_usage.get("output_tokens", 0)
            usage.add(prompt, completion)
            return usage

    return usage
