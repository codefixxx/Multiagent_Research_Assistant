"""Comprehensive tests for application error handling, classification, and resilience.

Tests:
- ApplicationError hierarchy and dictionary serialization
- Error classification for wrong model, invalid API key, rate limits, service outage
- Preflight model validation and connectivity checking
- Pipeline and worker exception handling and status persistence
- FastAPI global exception handlers and validation endpoints
"""

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.job_runner import ResearchJobService
from src.api.main import app
from src.core.exceptions import (
    ApplicationError,
    AuthenticationError,
    InvalidModelError,
    LLMConfigurationError,
    ModelError,
    ModelProviderError,
    PipelineExecutionError,
    RateLimitError,
    ToolExecutionError,
    classify_error,
)
from src.core.llm import validate_model_configuration, verify_model_connectivity
from src.schemas.api import ResearchRequest


def test_application_error_hierarchy_and_serialization():
    """Verify base ApplicationError and its subclasses produce structured dictionaries."""
    err = ApplicationError(
        message="Something went wrong",
        code="CUSTOM_CODE",
        status_code=418,
        suggestion="Take a tea break",
        details={"trace_id": "xyz-123"},
    )
    d = err.to_dict()
    assert d["error"] == "Something went wrong"
    assert d["code"] == "CUSTOM_CODE"
    assert d["status_code"] == 418
    assert d["suggestion"] == "Take a tea break"
    assert d["details"]["trace_id"] == "xyz-123"
    assert "timestamp" in d


def test_authentication_error_defaults():
    """Verify AuthenticationError sets 401 status and helpful suggestions."""
    err = AuthenticationError("Key rejected", provider="gemini")
    assert err.status_code == 401
    assert err.code == "INVALID_API_KEY"
    assert "Gemini" in err.suggestion
    assert err.details["provider"] == "gemini"


def test_invalid_model_error_defaults():
    """Verify InvalidModelError sets 400 status and identifies the model."""
    err = InvalidModelError("Model missing", model_name="gemini-fake-99", provider="gemini")
    assert err.status_code == 400
    assert err.code == "MODEL_NOT_FOUND"
    assert err.details["model_name"] == "gemini-fake-99"
    assert "gemini-fake-99" in err.suggestion


def test_classify_error_with_invalid_api_key_variations():
    """Verify classify_error correctly identifies API key authentication failures."""
    # Google format
    e1 = Exception("400 API_KEY_INVALID: The provided API key is invalid.")
    c1 = classify_error(e1, provider="gemini", model_name="gemini-2.5-flash")
    assert isinstance(c1, AuthenticationError)
    assert c1.code == "INVALID_API_KEY"
    assert "Gemini" in c1.suggestion

    # Groq format
    e2 = Exception("groq.AuthenticationError: 401 Invalid API Key")
    c2 = classify_error(e2, provider="groq")
    assert isinstance(c2, AuthenticationError)
    assert c2.code == "INVALID_API_KEY"
    assert "Groq" in c2.suggestion

    # OpenAI format
    e3 = Exception("openai.AuthenticationError: Incorrect API key provided: sk-bad***")
    c3 = classify_error(e3, model_name="gpt-4o")
    assert isinstance(c3, AuthenticationError)
    assert c3.code == "INVALID_API_KEY"
    assert "Openai" in c3.suggestion

    # Anthropic format
    e4 = Exception("anthropic.AuthenticationError: 401 invalid x-api-key")
    c4 = classify_error(e4, model_name="claude-3-5-sonnet")
    assert isinstance(c4, AuthenticationError)
    assert c4.code == "INVALID_API_KEY"


def test_classify_error_with_wrong_or_nonexistent_model():
    """Verify classify_error identifies non-existent or decommissioned model names."""
    # Google model not found
    e1 = Exception("404 models/gemini-3.5-flash-lite is not found for API version v1beta, or is not supported for generateContent. Call ListModels to see the list of available models.")
    c1 = classify_error(e1, model_name="gemini-3.5-flash-lite")
    assert isinstance(c1, InvalidModelError)
    assert c1.code == "MODEL_NOT_FOUND"
    assert "gemini-3.5-flash-lite" in c1.message
    assert "gemini-2.5-flash" in c1.suggestion

    # Groq model not found
    e2 = Exception("404 The model `llama-unknown` does not exist or you do not have access to it.")
    c2 = classify_error(e2, provider="groq", model_name="llama-unknown")
    assert isinstance(c2, InvalidModelError)
    assert c2.code == "MODEL_NOT_FOUND"
    assert "llama-3.3-70b-versatile" in c2.suggestion

    # OpenAI model not found
    e3 = Exception("The model `gpt-fake-99` does not exist")
    c3 = classify_error(e3, model_name="gpt-fake-99")
    assert isinstance(c3, InvalidModelError)
    assert c3.code == "MODEL_NOT_FOUND"
    assert "gpt-4o" in c3.suggestion


def test_classify_error_with_rate_limits():
    """Verify classify_error identifies quota exhaustion and rate limits."""
    e1 = Exception("429 RESOURCE_EXHAUSTED: Quota exceeded for quota metric 'GenerateContent requests'")
    c1 = classify_error(e1, provider="gemini")
    assert isinstance(c1, RateLimitError)
    assert c1.code == "RATE_LIMIT_EXCEEDED"
    assert c1.status_code == 429
    assert "rate limit or token quota" in c1.suggestion

    e2 = Exception("Rate limit reached for model `llama-3.3-70b-versatile` on tokens per minute (TPM).")
    c2 = classify_error(e2, provider="groq")
    assert isinstance(c2, RateLimitError)
    assert c2.code == "RATE_LIMIT_EXCEEDED"


def test_classify_error_with_service_unavailable():
    """Verify classify_error identifies provider downtime and connection issues."""
    e1 = Exception("503 Service Unavailable: Backends are temporarily overloaded.")
    c1 = classify_error(e1, provider="gemini")
    assert isinstance(c1, ModelProviderError)
    assert c1.code == "PROVIDER_UNAVAILABLE"
    assert c1.status_code == 502

    e2 = Exception("APIConnectionError: Connection error while requesting Groq API.")
    c2 = classify_error(e2, provider="groq")
    assert isinstance(c2, ModelProviderError)
    assert c2.code == "PROVIDER_UNAVAILABLE"


def test_classify_error_preserves_application_error():
    """Verify classify_error returns an existing ApplicationError directly with enriched details."""
    initial = AuthenticationError("Invalid key", provider="openai")
    classified = classify_error(initial, model_name="gpt-4o")
    assert classified is initial
    assert classified.details["model_name"] == "gpt-4o"


def test_validate_model_configuration():
    """Verify preflight model validation checks supported providers and key requirements."""
    # Unsupported provider
    with pytest.raises(InvalidModelError) as exc_info:
        validate_model_configuration(provider="unsupported_ai")
    assert "Unsupported LLM provider" in str(exc_info.value)
    assert exc_info.value.code == "MODEL_NOT_FOUND"

    # Missing OpenAI key
    with pytest.raises(AuthenticationError) as exc_info:
        validate_model_configuration(provider="openai", api_key="")
    assert "OPENAI_API_KEY is not configured" in str(exc_info.value)

    # Missing Anthropic key
    with pytest.raises(AuthenticationError) as exc_info:
        validate_model_configuration(provider="anthropic", api_key="")
    assert "ANTHROPIC_API_KEY is not configured" in str(exc_info.value)

    # Valid mock configuration
    validate_model_configuration(provider="mock")


@pytest.mark.asyncio
async def test_verify_model_connectivity_with_mock():
    """Verify that model connectivity check succeeds with mock provider."""
    res = await verify_model_connectivity(provider="mock")
    assert res["valid"] is True
    assert res["provider"] == "mock"
    assert "verified successfully" in res["message"]


@pytest.mark.asyncio
async def test_verify_model_connectivity_with_invalid_provider():
    """Verify that model connectivity check raises InvalidModelError for unknown providers."""
    with pytest.raises(InvalidModelError) as exc_info:
        await verify_model_connectivity(provider="nonexistent_provider")
    assert exc_info.value.code == "MODEL_NOT_FOUND"


@pytest.mark.asyncio
async def test_job_runner_catches_and_persists_model_failure():
    """Verify that ResearchJobService catches model failures, updates Redis status, and broadcasts job_failed."""
    from src.api.events import EventBroadcaster
    from tests.conftest import MockChatModel

    from langchain_core.runnables import RunnableLambda

    class FailingChatModel(MockChatModel):
        model_name: str = "gemini-unknown-33"

        def with_structured_output(self, schema, **kwargs):
            async def _fail(messages):
                raise Exception("404 models/gemini-unknown-33 is not found for API version v1beta")

            return RunnableLambda(_fail)

    broadcaster = EventBroadcaster()
    service = ResearchJobService(event_broadcaster=broadcaster, llm=FailingChatModel())
    await service.initialize()

    run_id = "test-failure-run-123"
    request = ResearchRequest(query="Test failure handling")

    # Execute job with the failing model
    await service.start_job(run_id=run_id, request=request, mode="embedded")

    # Wait for the background task to complete
    task = service._active_tasks.get(run_id)
    if task:
        await task

    # Verify status in Redis is failed with classified details
    status_resp = await service.get_status(run_id)
    assert status_resp is not None
    assert status_resp.status == "failed"
    assert status_resp.error_code == "MODEL_NOT_FOUND"
    assert "gemini-unknown-33" in (status_resp.error_message or "")
    assert status_resp.error_suggestion is not None
    assert "gemini-2.5-flash" in status_resp.error_suggestion

    # Verify audit trace also returns error information instead of crashing
    trace_resp = await service.get_audit_trace(run_id)
    assert trace_resp is not None
    assert trace_resp.status == "failed"
    assert trace_resp.error_code == "MODEL_NOT_FOUND"


@pytest.mark.asyncio
async def test_fastapi_exception_handlers():
    """Verify that FastAPI returns consistent structured JSON on ApplicationError and HTTPException."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 404 for unknown run
        r404 = await ac.get("/research/non-existent-run-xyz")
        assert r404.status_code == 404
        d404 = r404.json()
        assert d404["code"] == "HTTP_404"
        assert "not found" in d404["error"].lower()
        assert "suggestion" in d404

        # Validate-model endpoint with mock model
        r_val_ok = await ac.post("/research/validate-model", json={"provider": "mock"})
        assert r_val_ok.status_code == 200
        d_val_ok = r_val_ok.json()
        assert d_val_ok["valid"] is True
        assert d_val_ok["provider"] == "mock"

        # Validate-model endpoint with unsupported provider
        r_val_err = await ac.post("/research/validate-model", json={"provider": "bogus_ai"})
        assert r_val_err.status_code == 200
        d_val_err = r_val_err.json()
        assert d_val_err["valid"] is False
        assert d_val_err["code"] == "MODEL_NOT_FOUND"
        assert "bogus_ai" in d_val_err["message"]
        assert d_val_err["suggestion"] is not None
