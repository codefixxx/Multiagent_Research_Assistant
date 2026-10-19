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

    def __init__(self, redis_client: Any) -> None:
        self.redis = redis_client

    async def enqueue(
        self,
        run_id: str,
        request: ResearchRequest,
        priority: int = 0,
    ) -> dict[str, Any]:
        """Enqueue a research job payload into the Redis queue."""
        payload = {
            "run_id": run_id,
            "request": request.model_dump(mode="json"),
            "enqueued_at": datetime.now(UTC).isoformat(),
            "priority": priority,
        }
        await self.redis.rpush(QUEUE_KEY, json.dumps(payload))
        logger.info("Enqueued research job in Redis queue", run_id=run_id, query=request.query)
        return payload

    async def dequeue(self, timeout: float = 2.0) -> dict[str, Any] | None:
        """Pop the next available research job from the queue with timeout."""
        res = await self.redis.blpop(QUEUE_KEY, timeout=timeout)
        if not res:
            return None
        _, raw_payload = res
        payload_str = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else raw_payload
        return json.loads(payload_str)

    async def get_queue_length(self) -> int:
        """Return the number of waiting jobs in the queue."""
        return await self.redis.llen(QUEUE_KEY)

    async def clear_queue(self) -> None:
        """Purge all pending jobs from the queue."""
        await self.redis.delete(QUEUE_KEY)

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
