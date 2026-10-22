"""Cryptographic utilities for protecting sensitive API keys and secrets at rest.

Provides AES-256-GCM authenticated encryption with Associated Data (AEAD)
for queue job payloads, ensuring BYOK API keys are never stored in plaintext
inside Redis, logs, or persistent storage.
"""

import base64
import binascii
import hashlib
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.config import settings
from src.core.exceptions import ApplicationError
from src.core.logger import logger


class SecurityPayloadError(ApplicationError):
    """Raised when an encrypted secret payload cannot be authenticated or decrypted."""

    def __init__(
        self,
        message: str = "Failed to authenticate and decrypt secure payload.",
        code: str = "SECURITY_DECRYPTION_ERROR",
        status_code: int = 400,
        suggestion: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            suggestion=suggestion
            or "Verify QUEUE_ENCRYPTION_KEY and ensure payload was not tampered with.",
            details=details,
        )


def get_master_encryption_key(explicit_key: str | bytes | None = None) -> bytes:
    """Derive or resolve a 32-byte cryptographic key for AES-256-GCM.

    Resolution order:
    1. Explicit key parameter (if provided).
    2. settings.QUEUE_ENCRYPTION_KEY from environment or .env.
    3. Deterministic SHA-256 derivation bound to local persistence context.
    """
    candidate = explicit_key or getattr(settings, "QUEUE_ENCRYPTION_KEY", None)

    if candidate:
        if isinstance(candidate, str):
            candidate_clean = candidate.strip()
            # Check for 64-character hexadecimal key (256-bit)
            if len(candidate_clean) == 64:
                try:
                    return bytes.fromhex(candidate_clean)
                except ValueError:
                    pass

            # Check for 44-character base64 encoded key (256-bit)
            try:
                decoded = base64.b64decode(candidate_clean, validate=True)
                if len(decoded) == 32:
                    return decoded
            except (binascii.Error, ValueError):
                pass

            # Fall back to SHA-256 digest of utf-8 passphrase
            return hashlib.sha256(candidate_clean.encode("utf-8")).digest()

        if isinstance(candidate, (bytes, bytearray)):
            if len(candidate) == 32:
                return bytes(candidate)
            return hashlib.sha256(candidate).digest()

    # Fallback deterministic derivation for development/test environments
    salt = b"multiagent-research-assistant-secure-salt-v1:"
    context = (getattr(settings, "REDIS_URL", None) or "local-fallback").encode("utf-8")
    return hashlib.sha256(salt + context).digest()


def encrypt_secrets(
    secrets: dict[str, Any],
    aad: str | bytes = b"",
    key: bytes | None = None,
) -> str:
    """Encrypt a dictionary of secrets using AES-256-GCM with Associated Data (AAD).

    Returns a URL-safe Base64-encoded string structured as:
    `base64(12-byte nonce + ciphertext + 16-byte authentication tag)`
    """
    enc_key = key or get_master_encryption_key()
    aesgcm = AESGCM(enc_key)
    nonce = os.urandom(12)  # 96-bit standard nonce for GCM

    aad_bytes = aad.encode("utf-8") if isinstance(aad, str) else aad
    plaintext_bytes = json.dumps(secrets, separators=(",", ":")).encode("utf-8")

    ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, aad_bytes)
    payload = nonce + ciphertext
    return base64.urlsafe_b64encode(payload).decode("ascii")


def decrypt_secrets(
    token: str,
    aad: str | bytes = b"",
    key: bytes | None = None,
) -> dict[str, Any]:
    """Decrypt and authenticate a ciphertext token using AES-256-GCM and AAD.

    Raises:
        SecurityPayloadError: If the token is corrupted, tampered with,
        or bound to a mismatched AAD (e.g. wrong run_id).
    """
    enc_key = key or get_master_encryption_key()

    token_clean = token.strip()
    import re

    if not re.fullmatch(r"[A-Za-z0-9_\-=]+", token_clean):
        raise SecurityPayloadError(
            message="Invalid base64 encoding for encrypted secrets payload.",
            details={"token": token_clean[:10]},
        )

    try:
        missing_padding = len(token_clean) % 4
        if missing_padding:
            token_clean += "=" * (4 - missing_padding)
        raw = base64.urlsafe_b64decode(token_clean.encode("ascii"))
    except Exception as exc:
        raise SecurityPayloadError(
            message="Invalid base64 encoding for encrypted secrets payload.",
            details={"error": str(exc)},
        ) from exc

    if len(raw) < 28:  # 12 nonce + 16 tag minimum
        raise SecurityPayloadError(
            message="Encrypted payload truncated or corrupted (insufficient length).",
            details={"length": len(raw)},
        )

    nonce = raw[:12]
    ciphertext = raw[12:]
    aad_bytes = aad.encode("utf-8") if isinstance(aad, str) else aad
    aesgcm = AESGCM(enc_key)

    try:
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, aad_bytes)
    except InvalidTag as exc:
        logger.error("AES-256-GCM authentication tag verification failed")
        raise SecurityPayloadError(
            message="Payload authentication failed: ciphertext was tampered with or run_id mismatched.",
            details={"reason": "InvalidTag"},
        ) from exc
    except Exception as exc:
        raise SecurityPayloadError(
            message="Decryption failed due to unexpected error.",
            details={"error": str(exc)},
        ) from exc

    try:
        return json.loads(decrypted_bytes.decode("utf-8"))
    except Exception as exc:
        raise SecurityPayloadError(
            message="Decrypted secret payload contains invalid JSON.",
            details={"error": str(exc)},
        ) from exc


def zero_out_secrets(target: Any) -> None:
    """Best-effort in-memory zeroization of sensitive dictionaries or objects.

    Clears dictionary entries and overwrites known secret fields before deletion.
    """
    if isinstance(target, dict):
        for k in list(target.keys()):
            val = target[k]
            if isinstance(val, (dict, list)):
                zero_out_secrets(val)
            target[k] = None
        target.clear()
    elif hasattr(type(target), "model_fields"):
        for field_name in type(target).model_fields:
            if hasattr(target, field_name):
                try:
                    setattr(target, field_name, None)
                except Exception:
                    pass


def sanitize_text_secrets(text: str, custom_secrets: list[str] | None = None) -> str:
    """Scrub known API key patterns and custom secrets from text strings."""
    if not text or not isinstance(text, str):
        return text
    from src.core.logger import redact_secrets_text

    scrubbed = redact_secrets_text(text)
    if custom_secrets:
        for secret in custom_secrets:
            if secret and isinstance(secret, str) and len(secret) >= 8:
                scrubbed = scrubbed.replace(secret, "[REDACTED_API_KEY]")
    return scrubbed


def sanitize_report_secrets(report: Any, custom_secrets: list[str] | None = None) -> Any:
    """Recursively scrub secrets from all fields of a synthesized research report."""
    if report is None:
        return None

    if hasattr(report, "title") and report.title:
        report.title = sanitize_text_secrets(report.title, custom_secrets)
    if hasattr(report, "executive_summary") and report.executive_summary:
        report.executive_summary = sanitize_text_secrets(report.executive_summary, custom_secrets)
    if hasattr(report, "markdown_output") and report.markdown_output:
        report.markdown_output = sanitize_text_secrets(report.markdown_output, custom_secrets)

    if hasattr(report, "sections") and report.sections:
        for sec in report.sections:
            if hasattr(sec, "title") and sec.title:
                sec.title = sanitize_text_secrets(sec.title, custom_secrets)
            if hasattr(sec, "content") and sec.content:
                sec.content = sanitize_text_secrets(sec.content, custom_secrets)

    if hasattr(report, "citations") and report.citations:
        for cite in report.citations:
            for field in (
                "verified_claim",
                "claim",
                "verbatim_quote",
                "quote",
                "source_url",
                "url",
                "anchor_url",
            ):
                if hasattr(cite, field) and getattr(cite, field):
                    setattr(
                        cite, field, sanitize_text_secrets(getattr(cite, field), custom_secrets)
                    )

    return report


def sanitize_findings_secrets(
    findings: list[Any], custom_secrets: list[str] | None = None
) -> list[Any]:
    """Scrub secrets from extracted finding records."""
    if not findings:
        return findings
    for f in findings:
        for field in ("claim", "snippet", "verbatim_quote", "quote", "source_url"):
            if hasattr(f, field) and getattr(f, field):
                setattr(f, field, sanitize_text_secrets(getattr(f, field), custom_secrets))
    return findings
