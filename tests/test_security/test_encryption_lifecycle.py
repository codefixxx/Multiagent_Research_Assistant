"""Unit and integration tests for AES-256-GCM queue payload encryption and key lifecycle zeroization."""

import base64
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from src.core.security import (
    SecurityPayloadError,
    decrypt_secrets,
    encrypt_secrets,
    get_master_encryption_key,
    zero_out_secrets,
)
from src.persistence.queue import RedisJobQueue
from src.persistence.redis_saver import get_redis_client
from src.schemas.api import APIKeysConfig, ResearchRequest
from src.worker import ResearchWorker


def test_get_master_encryption_key_deterministic():
    """Verify master encryption key derivation produces a 32-byte key consistently."""
    key1 = get_master_encryption_key()
    key2 = get_master_encryption_key()
    assert isinstance(key1, bytes)
    assert len(key1) == 32
    assert key1 == key2


def test_get_master_encryption_key_formats():
    """Verify key derivation supports 64-character hex, 32-byte base64, and arbitrary strings."""
    # 64-char hex key (32 bytes)
    hex_key = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    derived_hex = get_master_encryption_key(explicit_key=hex_key)
    assert len(derived_hex) == 32
    assert derived_hex == bytes.fromhex(hex_key)

    # Base64 encoded 32-byte key
    raw_32 = b"A" * 32
    b64_key = base64.b64encode(raw_32).decode("ascii")
    derived_b64 = get_master_encryption_key(explicit_key=b64_key)
    assert len(derived_b64) == 32
    assert derived_b64 == raw_32

    # Arbitrary passphrase (hashed to 32 bytes)
    passphrase = "my-custom-secure-deployment-secret"
    derived_passphrase = get_master_encryption_key(explicit_key=passphrase)
    assert len(derived_passphrase) == 32


def test_aes_gcm_encrypt_decrypt_roundtrip():
    """Verify AES-256-GCM authenticated encryption and decryption roundtrip."""
    secrets = {
        "gemini": "AIzaSyTestGeminiKey1234567890",
        "openai": "sk-proj-TestOpenAIKey1234567890",
        "tavily": "tvly-TestTavilyKey1234567890",
    }
    run_id = f"run-{uuid.uuid4().hex[:8]}"

    token = encrypt_secrets(secrets, aad=run_id)
    assert isinstance(token, str)
    assert len(token) > 30

    decrypted = decrypt_secrets(token, aad=run_id)
    assert decrypted == secrets


def test_aes_gcm_tampering_fails():
    """Verify that tampering with any byte of ciphertext or tag causes decryption to fail."""
    secrets = {"groq": "gsk_TestGroqKey1234567890"}
    run_id = "run-tamper-test"

    token = encrypt_secrets(secrets, aad=run_id)
    raw = bytearray(base64.urlsafe_b64decode(token))

    # Tamper with the last byte (part of the 16-byte GCM authentication tag)
    raw[-1] ^= 0xFF
    tampered_token = base64.urlsafe_b64encode(raw).decode("ascii")

    with pytest.raises(SecurityPayloadError) as exc_info:
        decrypt_secrets(tampered_token, aad=run_id)
    assert "authentication failed" in exc_info.value.message.lower()


def test_aes_gcm_aad_binding_prevents_ciphertext_swapping():
    """Verify that attempting to decrypt ciphertext with a mismatched run_id fails."""
    secrets = {"anthropic": "sk-ant-TestAnthropicKey12345"}
    run_id_owner = "run-legit-owner-111"
    run_id_attacker = "run-swapped-target-222"

    token = encrypt_secrets(secrets, aad=run_id_owner)

    # Attempting to decrypt with a different run_id must fail cryptographic verification
    with pytest.raises(SecurityPayloadError) as exc_info:
        decrypt_secrets(token, aad=run_id_attacker)
    assert "authentication failed" in exc_info.value.message.lower()


def test_aes_gcm_invalid_tokens_raise_security_error():
    """Verify malformed or truncated base64 tokens raise structured SecurityPayloadError."""
    with pytest.raises(SecurityPayloadError) as exc1:
        decrypt_secrets("not-valid-base64!!!", aad="run-1")
    assert "invalid base64" in exc1.value.message.lower()

    truncated = base64.urlsafe_b64encode(b"short").decode("ascii")
    with pytest.raises(SecurityPayloadError) as exc2:
        decrypt_secrets(truncated, aad="run-1")
    assert "truncated" in exc2.value.message.lower()


def test_zero_out_secrets():
    """Verify zero_out_secrets wipes dictionaries and Pydantic models in place."""
    sensitive_dict = {
        "gemini": "AIzaSySecret",
        "nested": {"token": "bearer-secret-value"},
    }
    zero_out_secrets(sensitive_dict)
    assert len(sensitive_dict) == 0

    cfg = APIKeysConfig(gemini="AIzaSySecret12345", openai="sk-secret12345")
    assert cfg.gemini is not None
    zero_out_secrets(cfg)
    assert cfg.gemini is None
    assert cfg.openai is None


@pytest.mark.asyncio
async def test_redis_job_queue_encrypts_keys_at_rest():
    """Verify RedisJobQueue stores keys encrypted and never exposes plaintext secrets in Redis."""
    redis_client = await get_redis_client(force_fake=True)
    queue = RedisJobQueue(redis_client, queue_key=f"test:q:{uuid.uuid4().hex[:6]}")
    await queue.clear_queue()

    run_id = f"sec-run-{uuid.uuid4().hex[:8]}"
    raw_gemini_key = "AIzaSySuperSecretGeminiKeyAtRest123"
    raw_openai_key = "sk-proj-SuperSecretOpenAIKeyAtRest456"

    req = ResearchRequest(
        query="Verify at-rest queue encryption for BYOK credentials",
        api_keys=APIKeysConfig(
            gemini=SecretStr(raw_gemini_key),
            openai=SecretStr(raw_openai_key),
        ),
    )

    enqueued_payload = await queue.enqueue(run_id=run_id, request=req)
    assert enqueued_payload["run_id"] == run_id
    assert enqueued_payload["encrypted_keys"] is not None

    # Inspect raw data in Redis storage
    raw_redis_item = await redis_client.lindex(queue.queue_key, 0)
    raw_str = (
        raw_redis_item.decode("utf-8") if isinstance(raw_redis_item, bytes) else raw_redis_item
    )

    # 1. Plaintext keys MUST NOT exist anywhere in Redis raw storage
    assert raw_gemini_key not in raw_str
    assert raw_openai_key not in raw_str

    # 2. In the request dict inside Redis, SecretStr fields must be masked
    stored_dict = json.loads(raw_str)
    assert stored_dict["request"]["api_keys"]["gemini"] == "**********"
    assert stored_dict["request"]["api_keys"]["openai"] == "**********"

    # 3. Decrypting the payload with queue helper recovers the exact raw secrets
    decrypted = RedisJobQueue.extract_and_decrypt_keys(stored_dict)
    assert decrypted is not None
    assert decrypted["gemini"] == raw_gemini_key
    assert decrypted["openai"] == raw_openai_key

    await queue.clear_queue()


@pytest.mark.asyncio
async def test_worker_decrypts_and_processes_job_safely():
    """Verify worker receives encrypted job, decrypts keys for execution, and zeroes out memory."""
    redis_client = await get_redis_client(force_fake=True)
    queue = RedisJobQueue(redis_client, queue_key=f"test:worker:q:{uuid.uuid4().hex[:6]}")
    await queue.clear_queue()

    run_id = f"worker-test-run-{uuid.uuid4().hex[:6]}"
    raw_gemini_key = "AIzaSyWorkerDecryptionTestKey789"

    req = ResearchRequest(
        query="Worker key decryption and lifecycle test",
        api_keys=APIKeysConfig(gemini=SecretStr(raw_gemini_key)),
    )
    await queue.enqueue(run_id=run_id, request=req)

    # Create mock job service to inspect what request was passed into _execute_job
    mock_service = AsyncMock()
    mock_service.run_manager = AsyncMock()
    mock_service.default_llm = None

    worker = ResearchWorker(worker_id="test-secure-worker", job_service=mock_service, queue=queue)

    job_data = await queue.dequeue(timeout=1.0)
    assert job_data is not None

    # Process job with worker
    with patch.object(mock_service, "_execute_job", new_callable=AsyncMock) as mock_exec:
        await worker.process_job(job_data)

        assert mock_exec.called
        call_kwargs = mock_exec.call_args.kwargs
        executed_req: ResearchRequest = call_kwargs["request"]
        # Worker successfully reconstituted the real key as SecretStr for execution
        assert executed_req.api_keys is not None
        assert executed_req.api_keys.get_secret("gemini") == raw_gemini_key

    # Post-execution cleanup: encrypted_keys removed from job_data
    assert job_data.get("encrypted_keys") is None
    await queue.clear_queue()
