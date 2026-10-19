"""Unit tests for the Provider-Agnostic LLM Factory."""

import pytest
from langchain_core.messages import AIMessage

from pydantic import SecretStr

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


def test_detect_provider():
    from src.core.llm import detect_provider

    assert detect_provider("gemini-2.5-flash") == "gemini"
    assert detect_provider("models/gemini-pro") == "gemini"
    assert detect_provider("gpt-4o") == "openai"
    assert detect_provider("gpt-4o-mini") == "openai"
    assert detect_provider("o1-mini") == "openai"
    assert detect_provider("claude-3-5-sonnet") == "anthropic"
    assert detect_provider("claude-3-haiku-20240307") == "anthropic"
    assert detect_provider("llama-3.3-70b-versatile") == "groq"
    assert detect_provider("mock") == "mock"


def test_openai_instantiation_with_ephemeral_key():
    from langchain_openai import ChatOpenAI

    model = get_chat_model(
        model_name="gpt-4o-mini",
        api_key="sk-test-mock-openai-key-12345",
    )
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "gpt-4o-mini"
    assert isinstance(model.openai_api_key, SecretStr)
    assert model.openai_api_key.get_secret_value() == "sk-test-mock-openai-key-12345"


def test_anthropic_instantiation_with_ephemeral_key():
    from langchain_anthropic import ChatAnthropic

    model = get_chat_model(
        model_name="claude-3-5-sonnet-20241022",
        api_key="sk-ant-test-mock-anthropic-key-12345",
    )
    assert isinstance(model, ChatAnthropic)
    assert model.model == "claude-3-5-sonnet-20241022"
    assert isinstance(model.anthropic_api_key, SecretStr)
    assert model.anthropic_api_key.get_secret_value() == "sk-ant-test-mock-anthropic-key-12345"


def test_missing_api_key_raises_configuration_error():
    with pytest.raises(LLMConfigurationError) as exc_info:
        get_chat_model(provider="openai", api_key="")
    assert "OPENAI_API_KEY is not configured" in str(exc_info.value)

