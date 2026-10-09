"""Provider-Agnostic LLM Factory with support for Groq, Gemini, and Mock models."""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from pydantic import SecretStr

from src.config import settings
from src.core.logger import logger
from src.core.telemetry import TokenUsage


class LLMConfigurationError(Exception):
    """Raised when LLM credentials or configuration are invalid."""

    pass


def get_chat_model(
    provider: str | None = None,
    model_name: str | None = None,
    temperature: float = 0.1,
    max_tokens: int | None = None,
) -> BaseChatModel:
    """Instantiate and return a configured BaseChatModel based on settings and available keys.

    Supports:
        - "groq": Fast inference with Llama 3.3 70B (free tier).
        - "gemini": Deep context inference with Gemini 2.0 Flash (free tier).
        - "mock": Mock chat model for testing without API keys.
    """
    target_provider = (provider or settings.LLM_PROVIDER).lower()

    # Intelligent fallback if preferred provider lacks key
    if target_provider == "groq" and not settings.GROQ_API_KEY:
        if settings.GEMINI_API_KEY:
            logger.warning(
                "GROQ_API_KEY not found; falling back to Gemini provider",
                requested=target_provider,
                fallback="gemini",
            )
            target_provider = "gemini"
        else:
            raise LLMConfigurationError(
                "GROQ_API_KEY is not configured in .env or environment variables. "
                "Please set GROQ_API_KEY or switch LLM_PROVIDER to gemini/mock."
            )

    elif target_provider == "gemini" and not settings.GEMINI_API_KEY:
        if settings.GROQ_API_KEY:
            logger.warning(
                "GEMINI_API_KEY not found; falling back to Groq provider",
                requested=target_provider,
                fallback="groq",
            )
            target_provider = "groq"
        else:
            raise LLMConfigurationError(
                "GEMINI_API_KEY is not configured in .env or environment variables. "
                "Please set GEMINI_API_KEY or switch LLM_PROVIDER to groq/mock."
            )

    if target_provider == "groq":
        active_model = model_name or settings.LLM_MODEL or settings.GROQ_MODEL
        logger.info("Initializing Groq Chat Model", provider="groq", model=active_model)
        groq_key = SecretStr(settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None
        return ChatGroq(
            api_key=groq_key,
            model=active_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    elif target_provider == "gemini":
        active_model = model_name or settings.LLM_MODEL or settings.GEMINI_MODEL
        if active_model.startswith("models/"):
            active_model = active_model.replace("models/", "")
        logger.info("Initializing Gemini Chat Model", provider="gemini", model=active_model)
        return ChatGoogleGenerativeAI(
            google_api_key=settings.GEMINI_API_KEY,
            model=active_model,
            temperature=temperature,
            max_output_tokens=max_tokens,
            timeout=60.0,
            max_retries=3,
        )

    elif target_provider == "mock":
        from tests.conftest import MockChatModel

        logger.debug("Initializing Mock Chat Model")
        return MockChatModel()

    else:
        raise LLMConfigurationError(
            f"Unsupported LLM provider: '{target_provider}'. Supported: groq, gemini, mock."
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
