"""Unit tests for the Provider-Agnostic LLM Factory."""

import pytest
from langchain_core.messages import AIMessage

from src.core.llm import LLMConfigurationError, extract_token_usage, get_chat_model
from src.core.telemetry import TokenUsage


def test_mock_provider_instantiation():
    model = get_chat_model(provider="mock")
    assert model is not None
    assert model._llm_type == "mock"


def test_invalid_provider_raises_error():
    with pytest.raises(LLMConfigurationError) as exc_info:
        get_chat_model(provider="unsupported_provider")
    assert "Unsupported LLM provider" in str(exc_info.value)


def test_token_extraction_from_ai_message():
    msg = AIMessage(
        content="Testing",
        response_metadata={"token_usage": {"prompt_tokens": 120, "completion_tokens": 45}},
    )
    usage = extract_token_usage(msg)
    assert isinstance(usage, TokenUsage)
    assert usage.prompt_tokens == 120
    assert usage.completion_tokens == 45
    assert usage.total_tokens == 165


def test_token_extraction_empty_metadata():
    msg = AIMessage(content="Empty metadata")
    usage = extract_token_usage(msg)
    assert usage.total_tokens == 0
