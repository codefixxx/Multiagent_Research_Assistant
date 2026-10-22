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
    ModelProviderError,
    RateLimitError,
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
    e1 = Exception(
        "404 models/gemini-3.5-flash-lite is not found for API version v1beta, or is not supported for generateContent. Call ListModels to see the list of available models."
    )
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
    e1 = Exception(
        "429 RESOURCE_EXHAUSTED: Quota exceeded for quota metric 'GenerateContent requests'"
    )
    c1 = classify_error(e1, provider="gemini")
    assert isinstance(c1, RateLimitError)
    assert c1.code == "RATE_LIMIT_EXCEEDED"
    assert c1.status_code == 429
    assert "rate limit or token quota" in c1.suggestion

    e2 = Exception(
        "Rate limit reached for model `llama-3.3-70b-versatile` on tokens per minute (TPM)."
    )
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
    from langchain_core.runnables import RunnableLambda

    from src.api.events import EventBroadcaster
    from tests.conftest import MockChatModel

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
    from src.api.job_runner import job_service

    await job_service.initialize(force_new=True)
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


def test_classify_error_context_length_exceeded():
    """Verify classify_error identifies context window and token length exceedance."""
    from src.core.exceptions import ContextLengthExceededError

    e_groq = Exception(
        "groq.BadRequestError: 400 context_length_exceeded: maximum context length is 8192 tokens. However, your request has 12400 tokens"
    )
    c_groq = classify_error(e_groq, model_name="llama-3.1-8b-instant")
    assert isinstance(c_groq, ContextLengthExceededError)
    assert c_groq.code == "CONTEXT_LENGTH_EXCEEDED"
    assert c_groq.status_code == 400
    assert "context window" in c_groq.suggestion.lower()

    e_gemini = Exception(
        "google.api_core.exceptions.InvalidArgument: 400 Request payload size exceeds the limit"
    )
    c_gemini = classify_error(e_gemini, model_name="gemini-2.5-flash")
    assert isinstance(c_gemini, ContextLengthExceededError)
    assert c_gemini.code == "CONTEXT_LENGTH_EXCEEDED"


def test_classify_error_content_moderation_safety():
    """Verify classify_error identifies model provider safety and content moderation blocks."""
    from src.core.exceptions import ContentModerationError

    e_safety = Exception(
        "ValueError: The Candidate was blocked due to SAFETY. finish_reason: SAFETY"
    )
    c_safety = classify_error(e_safety, model_name="gemini-2.5-flash")
    assert isinstance(c_safety, ContentModerationError)
    assert c_safety.code == "CONTENT_MODERATION_BLOCKED"
    assert c_safety.status_code == 400
    assert "safety" in c_safety.suggestion.lower()

    e_openai = Exception(
        "openai.BadRequestError: 400 content_policy_violation: Your request was rejected due to content policy"
    )
    c_openai = classify_error(e_openai, model_name="gpt-4o")
    assert isinstance(c_openai, ContentModerationError)
    assert c_openai.code == "CONTENT_MODERATION_BLOCKED"


def test_classify_error_schema_validation():
    """Verify classify_error identifies structured output schema failures."""
    from src.core.exceptions import SchemaValidationError

    e_pydantic = Exception(
        "pydantic.ValidationError: 2 validation errors for ResearcherOutput: findings field required"
    )
    c_pydantic = classify_error(e_pydantic, node="researcher")
    assert isinstance(c_pydantic, SchemaValidationError)
    assert c_pydantic.code == "SCHEMA_VALIDATION_ERROR"
    assert c_pydantic.status_code == 500


@pytest.mark.asyncio
async def test_planner_handles_parsed_none_gracefully():
    """Verify planner specialist agent raises SchemaValidationError when model returns parsed=None."""
    from langchain_core.runnables import RunnableLambda

    from src.agents.planner import plan_research
    from src.core.exceptions import SchemaValidationError
    from tests.conftest import MockChatModel

    class MalformedChatModel(MockChatModel):
        def with_structured_output(self, schema, **kwargs):
            async def _fake_malformed(messages):
                return {
                    "raw": "Malformed JSON {broken",
                    "parsed": None,
                    "parsing_error": "JSONDecodeError: Expecting value: line 1 column 17",
                }

            return RunnableLambda(_fake_malformed)

    with pytest.raises(SchemaValidationError) as excinfo:
        await plan_research("What is quantum computing?", llm=MalformedChatModel())

    assert excinfo.value.code == "SCHEMA_VALIDATION_ERROR"
    assert "JSONDecodeError" in excinfo.value.message or "JSONDecodeError" in str(
        excinfo.value.details
    )
    assert excinfo.value.details.get("node") == "planner"


@pytest.mark.asyncio
async def test_job_runner_failure_resilient_to_redis_disconnect(monkeypatch):
    """Verify job runner completes failure handling and broadcasts event even if Redis is unreachable."""
    from unittest.mock import AsyncMock

    from src.api.events import EventBroadcaster
    from src.schemas.api import ResearchRequest
    from tests.conftest import MockChatModel

    class CrashingModel(MockChatModel):
        def with_structured_output(self, schema, **kwargs):
            from langchain_core.runnables import RunnableLambda

            async def _crash(messages):
                raise Exception("401 Invalid API Key")

            return RunnableLambda(_crash)

    received_events = []

    class CapturingBroadcaster(EventBroadcaster):
        async def broadcast(self, run_id, event, data):
            received_events.append((run_id, event, data))

    broadcaster = CapturingBroadcaster()
    service = ResearchJobService(event_broadcaster=broadcaster, llm=CrashingModel())
    await service.initialize()

    # Simulate Redis connection failure on update_run_status
    import redis.exceptions

    mock_failing_update = AsyncMock(
        side_effect=redis.exceptions.ConnectionError("Redis connection lost")
    )
    monkeypatch.setattr(service.run_manager, "update_run_status", mock_failing_update)

    run_id = "test-redis-disconnect-run"
    await service.start_job(
        run_id=run_id, request=ResearchRequest(query="Testing Redis disconnect"), mode="embedded"
    )

    task = service._active_tasks.get(run_id)
    if task:
        await task

    # Assert that despite Redis failure, the broadcaster successfully delivered the job_failed event
    failed_events = [ev for ev in received_events if ev[1] == "job_failed"]
    assert len(failed_events) >= 1
    run_id_ev, evt_name, evt_data = failed_events[0]
    assert evt_data["status"] == "failed"
    assert evt_data["code"] == "INVALID_API_KEY"
