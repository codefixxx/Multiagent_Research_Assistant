"""Security tests for BYOK credential isolation, Pydantic SecretStr masking, and logger redaction."""

import pytest
from pydantic import SecretStr

from src.core.llm import get_chat_model, validate_model_configuration
from src.core.logger import (
    redact_secrets_processor,
    redact_secrets_text,
    sanitize_log_value,
)
from src.schemas.api import APIKeysConfig, ResearchRequest


def test_api_keys_config_masks_secrets_in_str_and_repr():
    """Verify APIKeysConfig does not leak credentials when printed or converted to string."""
    raw_key = "AIzaSyTestGeminiKey1234567890abcdef"
    config = APIKeysConfig(
        gemini=raw_key,
        openai="sk-proj-testOpenAIKey1234567890abcdef",
        anthropic="sk-ant-testAnthropicKey1234567890abcdef",
        groq="gsk_testGroqKey1234567890abcdef",
        tavily="tvly-testTavilyKey1234567890abcdef",
    )

    # 1. str() and repr() must mask secrets
    str_val = str(config)
    repr_val = repr(config)
    assert raw_key not in str_val
    assert raw_key not in repr_val
    assert "**********" in str_val
    assert "**********" in repr_val

    # 2. model_dump() masks values
    dumped = config.model_dump()
    for provider, secret in dumped.items():
        assert isinstance(secret, SecretStr)
        assert secret.get_secret_value().startswith(("AIza", "sk-", "gsk_", "tvly-"))

    # 3. model_dump(mode="json") outputs masked string
    json_dumped = config.model_dump(mode="json")
    for provider, val in json_dumped.items():
        assert val == "**********"


def test_api_keys_config_exposed_methods_for_safe_extraction():
    """Verify get_secret and to_exposed_dict explicitly return raw strings for LLM constructors."""
    config = APIKeysConfig(
        gemini="AIzaSyTestGeminiKey1234567890abcdef",
        groq="gsk_testGroqKey1234567890abcdef",
    )

    assert config.get_secret("gemini") == "AIzaSyTestGeminiKey1234567890abcdef"
    assert config.get_secret("groq") == "gsk_testGroqKey1234567890abcdef"
    assert config.get_secret("openai") is None

    exposed = config.to_exposed_dict()
    assert exposed["gemini"] == "AIzaSyTestGeminiKey1234567890abcdef"
    assert exposed["groq"] == "gsk_testGroqKey1234567890abcdef"
    assert exposed["openai"] is None


def test_research_request_serialization_masks_api_keys():
    """Verify ResearchRequest dumps mask user API keys in json mode."""
    req = ResearchRequest(
        query="Research quantum supremacy",
        api_keys=APIKeysConfig(gemini="AIzaSyTestGeminiKey1234567890abcdef"),
    )
    dumped_json = req.model_dump(mode="json")
    assert dumped_json["api_keys"]["gemini"] == "**********"
    assert "AIzaSyTestGeminiKey1234567890abcdef" not in str(dumped_json)


@pytest.mark.parametrize(
    "raw_secret,provider_tag",
    [
        ("AIzaSy1234567890abcdefghijklmnopqrstuvwxyz", "gemini"),
        ("sk-1234567890abcdefghijklmnopqrstuvwx", "openai_legacy"),
        ("sk-proj-1234567890abcdefghijklmnopqrstuvwxyz12345", "openai_project"),
        ("sk-ant-api03-1234567890abcdefghijklmnopqrstuvwxyz", "anthropic"),
        ("gsk_1234567890abcdefghijklmnopqrstuvwxyz123456", "groq"),
        ("tvly-1234567890abcdefghijklmnopqrstuvwxyz", "tavily"),
        ("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-IDc", "bearer"),
    ],
)
def test_redact_secrets_text(raw_secret, provider_tag):
    """Verify regex redacts all recognized API key patterns from text."""
    sample_text = (
        f"Connecting to {provider_tag} with authorization token: {raw_secret} for model call"
    )
    redacted = redact_secrets_text(sample_text)
    assert raw_secret not in redacted
    assert "[REDACTED_API_KEY]" in redacted


def test_sanitize_log_value_recursive():
    """Verify recursive sanitization traverses nested dictionaries, lists, and tuples."""
    nested_data = {
        "run_id": "test-run-123",
        "nested": {
            "credentials": [
                "sk-ant-1234567890abcdefghijklmnopqrstuvwxyz",
                "AIzaSy1234567890abcdefghijklmnopqrstuvwxyz",
            ],
            "tuple_creds": ("gsk_1234567890abcdefghijklmnopqrstuvwxyz",),
        },
        "query": "Safe research query",
    }
    sanitized = sanitize_log_value(nested_data)
    assert sanitized["run_id"] == "test-run-123"
    assert sanitized["query"] == "Safe research query"
    assert sanitized["nested"]["credentials"] == ["[REDACTED_API_KEY]", "[REDACTED_API_KEY]"]
    assert sanitized["nested"]["tuple_creds"] == ("[REDACTED_API_KEY]",)


def test_structlog_redaction_processor_execution():
    """Verify that structlog events have secrets scrubbed before reaching any renderer."""
    event_dict = {
        "event": "Dispatching model request with key AIzaSy1234567890abcdefghijklmnopqrstuvwxyz",
        "api_key": "sk-proj-test123456789012345678901234567890",
        "status": "active",
    }
    processed = redact_secrets_processor(None, "info", event_dict)
    assert "AIzaSy" not in processed["event"]
    assert "[REDACTED_API_KEY]" in processed["event"]
    assert processed["api_key"] == "[REDACTED_API_KEY]"
    assert processed["status"] == "active"


def test_get_chat_model_accepts_secret_str():
    """Verify get_chat_model cleanly accepts SecretStr without type error."""
    secret = SecretStr("mock-key-for-test")
    # For mock provider, key is accepted without error
    model = get_chat_model(provider="mock", api_key=secret)
    assert model is not None

    # validate_model_configuration accepts SecretStr
    validate_model_configuration(provider="mock", api_key=secret)


def test_require_byok_blocks_server_env_fallback(monkeypatch):
    """Verify that when REQUIRE_BYOK is True, get_chat_model and validate_model_configuration refuse fallback."""
    from src.config import settings
    from src.core.exceptions import AuthenticationError

    monkeypatch.setattr(settings, "REQUIRE_BYOK", True)

    # 1. Without client key, must raise AuthenticationError with BYOK_REQUIRED code
    with pytest.raises(AuthenticationError) as exc_info:
        validate_model_configuration(provider="gemini", api_key=None)
    assert exc_info.value.code == "BYOK_REQUIRED"
    assert "Bring Your Own Key required" in exc_info.value.message

    with pytest.raises(AuthenticationError) as exc_info_llm:
        get_chat_model(provider="gemini", api_key=None)
    assert exc_info_llm.value.code == "BYOK_REQUIRED"

    # 2. When client key is provided, validation passes
    validate_model_configuration(
        provider="gemini", api_key="AIzaSyTestClientProvidedKey12345678"
    )


@pytest.mark.asyncio
async def test_require_byok_enforced_at_api_route(monkeypatch):
    """Verify that POST /research rejects requests missing keys when REQUIRE_BYOK is active."""
    from httpx import ASGITransport, AsyncClient

    from src.api.main import app
    from src.config import settings

    monkeypatch.setattr(settings, "REQUIRE_BYOK", True)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # Check /health reports require_byok
        health_resp = await client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["require_byok"] is True

        # Submit research without keys
        res = await client.post("/research", json={"query": "Test BYOK enforcement"})
        assert res.status_code == 401
        data = res.json()
        assert data["code"] == "BYOK_REQUIRED"
        assert "Bring Your Own Key required" in data["error"]
