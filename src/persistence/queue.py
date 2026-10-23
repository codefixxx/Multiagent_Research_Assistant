"""Distributed Redis job queue and worker registry for decoupled research execution."""

import json
from datetime import UTC, datetime
from typing import Any

from src.core.logger import logger
from src.schemas.api import ResearchRequest

QUEUE_KEY = "research:queue:jobs"
WORKERS_SET = "research:workers:active"


class RedisJobQueue:
    """Manages enqueueing, dequeueing, cancellation, and heartbeat registry in Redis."""

    def __init__(self, redis_client: Any, queue_key: str = QUEUE_KEY) -> None:
        self.redis = redis_client
        self.queue_key = queue_key

    async def enqueue(
        self,
        run_id: str,
        request: ResearchRequest,
        priority: int = 0,
    ) -> dict[str, Any]:
        """Enqueue a research job payload into the Redis queue with encrypted BYOK secrets."""
        encrypted_keys = None
        if (
            request.api_keys
            and hasattr(request.api_keys, "has_keys")
            and request.api_keys.has_keys()
        ):
            from src.core.security import encrypt_secrets

            exposed = request.api_keys.to_exposed_dict()
            encrypted_keys = encrypt_secrets(exposed, aad=run_id)

        payload = {
            "run_id": run_id,
            "request": request.model_dump(mode="json"),
            "encrypted_keys": encrypted_keys,
            "enqueued_at": datetime.now(UTC).isoformat(),
            "priority": priority,
        }
        await self.redis.rpush(self.queue_key, json.dumps(payload))
        logger.info("Enqueued research job in Redis queue", run_id=run_id, query=request.query)
        return payload

    @staticmethod
    def extract_and_decrypt_keys(job_data: dict[str, Any]) -> dict[str, Any] | None:
        """Decrypt ephemeral BYOK keys from a dequeued job payload using AES-256-GCM and run_id AAD."""
        encrypted_keys = job_data.get("encrypted_keys")
        run_id = job_data.get("run_id")
        if not encrypted_keys or not run_id:
            return None
        from src.core.security import decrypt_secrets

        return decrypt_secrets(encrypted_keys, aad=run_id)

    async def dequeue(self, timeout: float = 2.0) -> dict[str, Any] | None:
        """Pop the next available research job from the queue with timeout."""
        res = await self.redis.blpop(self.queue_key, timeout=timeout)
        if not res:
            return None
        _, raw_payload = res
        payload_str = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else raw_payload
        return json.loads(payload_str)

    async def get_queue_length(self) -> int:
        """Return the number of waiting jobs in the queue."""
        return await self.redis.llen(self.queue_key)

    async def clear_queue(self) -> None:
        """Purge all pending jobs from the queue."""
        await self.redis.delete(self.queue_key)

    async def register_worker(
        self,
        worker_id: str,
        metadata: dict[str, Any] | None = None,
        ttl: int = 15,
    ) -> None:
        """Register or refresh worker heartbeat in Redis."""
        key = f"research:worker:{worker_id}"
        meta = {
            "worker_id": worker_id,
            "heartbeat": datetime.now(UTC).isoformat(),
            **(metadata or {}),
        }
        await self.redis.set(key, json.dumps(meta), ex=ttl)
        await self.redis.sadd(WORKERS_SET, worker_id)

    async def deregister_worker(self, worker_id: str) -> None:
        """Remove worker upon graceful shutdown."""
        await self.redis.delete(f"research:worker:{worker_id}")
        await self.redis.srem(WORKERS_SET, worker_id)

    async def get_active_workers(self) -> list[dict[str, Any]]:
        """Return all currently active worker nodes with valid heartbeats."""
        worker_ids = await self.redis.smembers(WORKERS_SET)
        active: list[dict[str, Any]] = []
        stale: list[str] = []
        for wid in worker_ids:
            wid_str = wid.decode("utf-8") if isinstance(wid, bytes) else wid
            raw = await self.redis.get(f"research:worker:{wid_str}")
            if raw:
                meta = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
                active.append(meta)
            else:
                stale.append(wid_str)
        if stale:
            for s in stale:
                await self.redis.srem(WORKERS_SET, s)
        return active

    async def request_cancel(self, run_id: str) -> None:
        """Set a cancellation flag in Redis for this run ID."""
        await self.redis.set(f"research:run:{run_id}:cancel", "1", ex=3600)

    async def is_cancelled(self, run_id: str) -> bool:
        """Check whether cancellation was requested for this run ID."""
        flag = await self.redis.get(f"research:run:{run_id}:cancel")
        return bool(flag)
