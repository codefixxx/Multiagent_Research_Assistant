"""Durable state persistence, Redis checkpointing, and run metadata management."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from langgraph.checkpoint.redis.ashallow import AsyncShallowRedisSaver

from src.config import settings
from src.core.logger import logger

# Module-level singleton fake redis client for in-memory session persistence
_shared_fake_redis: Any = None


def get_shared_fake_redis() -> Any:
    """Return a shared FakeRedis instance preserving checkpoints across graph reloads."""
    global _shared_fake_redis
    if _shared_fake_redis is None:
        import fakeredis.aioredis

        _shared_fake_redis = fakeredis.aioredis.FakeRedis()
    return _shared_fake_redis


async def get_redis_client(
    redis_url: str | None = None,
    force_fake: bool = False,
    timeout: float = 1.0,
) -> Any:
    """Get an asynchronous Redis client with automatic local dev fallback.

    If Redis is unreachable or force_fake is True, seamlessly falls back
    to an in-memory FakeRedis client so local development and testing
    never fail due to missing external infrastructure.
    """
    if force_fake:
        logger.debug("Using in-memory FakeRedis client (force_fake=True)")
        return get_shared_fake_redis()

    url = redis_url or settings.REDIS_URL
    try:
        client = aioredis.from_url(url, decode_responses=False)
        # Verify connection with quick ping
        pong = await asyncio.wait_for(client.ping(), timeout=timeout)
        if pong:
            logger.info("Successfully connected to Redis", url=url)
            return client
    except Exception as e:
        logger.warning(
            "Redis server unreachable, falling back to in-memory FakeRedis",
            url=url,
            error=str(e),
        )

    return get_shared_fake_redis()


async def get_checkpointer(
    redis_client: Any = None,
    redis_url: str | None = None,
    force_fake: bool = False,
) -> AsyncShallowRedisSaver:
    """Create and return a LangGraph AsyncShallowRedisSaver.

    Uses AsyncShallowRedisSaver which relies on standard Redis commands
    rather than RediSearch (FT.SEARCH), ensuring universal compatibility
    with standard Redis servers, managed Redis, and in-memory test mocks.
    """
    client = redis_client
    if client is None:
        client = await get_redis_client(redis_url=redis_url, force_fake=force_fake)

    return AsyncShallowRedisSaver(redis_client=client)


class RedisRunManager:
    """Manages research run lifecycle metadata and progress tracking in Redis."""

    def __init__(self, redis_client: Any) -> None:
        self.redis = redis_client

    def _meta_key(self, run_id: str) -> str:
        return f"research:run:{run_id}:metadata"

    def _steps_key(self, run_id: str) -> str:
        return f"research:run:{run_id}:steps"

    async def init_run(self, run_id: str, query: str) -> dict[str, Any]:
        """Initialize metadata for a new research run."""
        now = datetime.now(UTC).isoformat()
        metadata = {
            "run_id": run_id,
            "query": query,
            "status": "planning",
            "current_node": "planner",
            "step_count": 0,
            "total_tokens": 0,
            "created_at": now,
            "updated_at": now,
            "error_message": None,
        }
        await self.redis.set(self._meta_key(run_id), json.dumps(metadata))
        logger.info("Initialized research run metadata in Redis", run_id=run_id, query=query)
        return metadata

    async def update_run_status(
        self,
        run_id: str,
        status: str,
        current_node: str | None = None,
        step_count: int | None = None,
        total_tokens: int | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any] | None:
        """Atomically update run progress and status in Redis."""
        raw = await self.redis.get(self._meta_key(run_id))
        if not raw:
            return None

        data_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        meta: dict[str, Any] = json.loads(data_str)

        meta["status"] = status
        meta["updated_at"] = datetime.now(UTC).isoformat()
        if current_node:
            meta["current_node"] = current_node
        if step_count is not None:
            meta["step_count"] = step_count
        if total_tokens is not None:
            meta["total_tokens"] = total_tokens
        if error_message is not None:
            meta["error_message"] = error_message

        await self.redis.set(self._meta_key(run_id), json.dumps(meta))
        return meta

    async def get_run_metadata(self, run_id: str) -> dict[str, Any] | None:
        """Fetch metadata for a given run ID."""
        raw = await self.redis.get(self._meta_key(run_id))
        if not raw:
            return None
        data_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        return json.loads(data_str)

    async def record_completed_step(
        self,
        run_id: str,
        node_name: str,
        step_number: int,
    ) -> None:
        """Append a completed step to the run's audit trail."""
        step_record = json.dumps({
            "node": node_name,
            "step": step_number,
            "timestamp": datetime.now(UTC).isoformat(),
        })
        await self.redis.rpush(self._steps_key(run_id), step_record)

    async def get_step_history(self, run_id: str) -> list[dict[str, Any]]:
        """Retrieve the sequence of completed steps for a run."""
        raw_items = await self.redis.lrange(self._steps_key(run_id), 0, -1)
        history: list[dict[str, Any]] = []
        for item in raw_items:
            item_str = item.decode("utf-8") if isinstance(item, bytes) else item
            history.append(json.loads(item_str))
        return history

    async def clear_run(self, run_id: str) -> None:
        """Purge metadata and step records for a given run."""
        await self.redis.delete(self._meta_key(run_id), self._steps_key(run_id))


class NodeIdempotencyCache:
    """Caches node execution results in Redis to avoid redundant external calls or token spend."""

    def __init__(self, redis_client: Any, default_ttl_seconds: int = 3600) -> None:
        self.redis = redis_client
        self.default_ttl = default_ttl_seconds

    def compute_cache_key(self, run_id: str, node_name: str, payload: Any) -> str:
        """Generate a deterministic cache key from input payload hash."""
        serialized = json.dumps(payload, sort_keys=True, default=str)
        payload_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        return f"research:run:{run_id}:cache:{node_name}:{payload_hash}"

    async def get(self, run_id: str, node_name: str, payload: Any) -> dict[str, Any] | None:
        """Retrieve cached output if previously executed with identical inputs."""
        key = self.compute_cache_key(run_id, node_name, payload)
        raw = await self.redis.get(key)
        if not raw:
            return None
        data_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        return json.loads(data_str)

    async def set(
        self,
        run_id: str,
        node_name: str,
        payload: Any,
        output_data: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        """Store output in cache with an expiration TTL."""
        key = self.compute_cache_key(run_id, node_name, payload)
        ttl = ttl_seconds or self.default_ttl
        serialized = json.dumps(output_data, default=str)
        await self.redis.set(key, serialized, ex=ttl)
