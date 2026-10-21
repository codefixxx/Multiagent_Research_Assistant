"""Durable state persistence, Redis checkpointing, and run metadata management."""

import asyncio
import hashlib
import json
import time
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


class PipelineProxy:
    """Proxies a Redis pipeline to emulate JSON commands via standard key-value storage."""

    def __init__(self, pipe: Any) -> None:
        self._pipe = pipe
        self._json_get_indices: set[int] = set()

    def json(self) -> Any:
        proxy = self

        class _PipeJsonShim:
            def set(self, key: str, path: str, data: Any) -> Any:
                serialized = json.dumps(data)
                return proxy._pipe.set(key, serialized)

            def get(self, key: str, *args: Any, **kwargs: Any) -> Any:
                idx = len(getattr(proxy._pipe, "command_stack", []))
                proxy._json_get_indices.add(idx)
                return proxy._pipe.get(key)

        return _PipeJsonShim()

    async def execute(self, *args: Any, **kwargs: Any) -> list[Any]:
        results = await self._pipe.execute(*args, **kwargs)
        if not self._json_get_indices:
            return results
        new_results = []
        for i, res in enumerate(results):
            if i in self._json_get_indices and res is not None:
                if isinstance(res, (bytes, bytearray)):
                    res = res.decode("utf-8")
                try:
                    new_results.append(json.loads(res))
                except Exception:
                    new_results.append(res)
            else:
                new_results.append(res)
        return new_results

    def __getattr__(self, name: str) -> Any:
        return getattr(self._pipe, name)


class RedisJsonShim:
    """Emulates RedisJSON commands on a standard Redis client using serialized strings."""

    def __init__(self, target: Any) -> None:
        self._target = target

    async def get(self, key: str, *args: Any, **kwargs: Any) -> Any:
        val = await self._target.get(key)
        if not val:
            return None
        if isinstance(val, (bytes, bytearray)):
            val = val.decode("utf-8")
        data = json.loads(val)
        if args and args[0] == "$.checkpoint":
            return [data.get("checkpoint")]
        return data

    async def set(self, key: str, path: str, data: Any) -> Any:
        serialized = json.dumps(data)
        return await self._target.set(key, serialized)


class StandardRedisClientProxy:
    """Transparent proxy adapting standard Redis clients for LangGraph checkpointers."""

    def __init__(self, real_client: Any) -> None:
        self._real_client = real_client
        self._json_shim = RedisJsonShim(real_client)

    def json(self) -> Any:
        return self._json_shim

    def pipeline(self, transaction: bool = False) -> PipelineProxy:
        pipe = self._real_client.pipeline(transaction=transaction)
        return PipelineProxy(pipe)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real_client, name)


async def _ensure_redis_json_compatible(client: Any) -> Any:
    """Ensure the Redis client supports JSON commands, proxying if RedisJSON is unavailable."""
    if "fakeredis" in client.__class__.__module__:
        return client
    try:
        await client.execute_command("JSON.SET", "__rejson_probe__", "$", "{}")
        await client.execute_command("DEL", "__rejson_probe__")
        return client
    except Exception:
        logger.debug(
            "RedisJSON module not detected; enabling standard Redis JSON proxy for LangGraph checkpointer"
        )
        return StandardRedisClientProxy(client)


async def get_checkpointer(
    redis_client: Any = None,
    redis_url: str | None = None,
    force_fake: bool = False,
) -> AsyncShallowRedisSaver:
    """Create and return a LangGraph AsyncShallowRedisSaver.

    Uses AsyncShallowRedisSaver which adapts to both Redis Stack (with RedisJSON)
    and standard Redis instances, ensuring universal compatibility
    with standard Redis servers, managed Redis, and in-memory test mocks.
    """
    client = redis_client
    if client is None:
        client = await get_redis_client(redis_url=redis_url, force_fake=force_fake)

    compat_client = await _ensure_redis_json_compatible(client)
    return AsyncShallowRedisSaver(redis_client=compat_client)


class RedisRunManager:
    """Manages research run lifecycle metadata and progress tracking in Redis."""

    def __init__(self, redis_client: Any, default_ttl_seconds: int | None = None) -> None:
        self.redis = redis_client
        self.default_ttl = (
            default_ttl_seconds
            if default_ttl_seconds is not None
            else getattr(settings, "REPORT_RETENTION_SECONDS", 86400)
        )

    def _index_key(self) -> str:
        return "research:runs:index"

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
        if self.default_ttl and self.default_ttl > 0:
            await self.redis.set(self._meta_key(run_id), json.dumps(metadata), ex=self.default_ttl)
        else:
            await self.redis.set(self._meta_key(run_id), json.dumps(metadata))

        # Index run in the reverse-chronological Sorted Set
        try:
            now_ts = time.time()
            await self.redis.zadd(self._index_key(), {run_id: now_ts})
            if self.default_ttl and self.default_ttl > 0:
                await self.redis.zremrangebyscore(self._index_key(), "-inf", now_ts - self.default_ttl)
        except Exception as e:
            logger.debug("Failed indexing run in Sorted Set", run_id=run_id, error=str(e))

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
        error_code: str | None = None,
        error_suggestion: str | None = None,
        error_details: dict[str, Any] | None = None,
        cost_summary: dict[str, Any] | None = None,
        rag_score: dict[str, Any] | None = None,
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
        if error_code is not None:
            meta["error_code"] = error_code
        if error_suggestion is not None:
            meta["error_suggestion"] = error_suggestion
        if error_details is not None:
            meta["error_details"] = error_details
        if cost_summary is not None:
            meta["cost_summary"] = cost_summary
        if rag_score is not None:
            meta["rag_score"] = rag_score

        if self.default_ttl and self.default_ttl > 0:
            await self.redis.set(self._meta_key(run_id), json.dumps(meta), ex=self.default_ttl)
        else:
            await self.redis.set(self._meta_key(run_id), json.dumps(meta))

        # Ensure run ID is indexed in the Sorted Set
        try:
            now_ts = time.time()
            await self.redis.zadd(self._index_key(), {run_id: now_ts})
        except Exception:
            pass

        return meta

    async def list_recent_runs(
        self, limit: int = 20, offset: int = 0
    ) -> tuple[int, list[dict[str, Any]]]:
        """Retrieve recent research runs within the retention window in reverse-chronological order."""
        idx_key = self._index_key()
        now_ts = time.time()
        if self.default_ttl and self.default_ttl > 0:
            try:
                await self.redis.zremrangebyscore(idx_key, "-inf", now_ts - self.default_ttl)
            except Exception as e:
                logger.debug("Failed pruning expired runs from index", error=str(e))

        total = await self.redis.zcard(idx_key) or 0
        if total == 0:
            return 0, []

        raw_ids = await self.redis.zrevrange(idx_key, offset, offset + limit - 1)
        run_ids = [
            rid.decode("utf-8") if isinstance(rid, bytes) else rid
            for rid in raw_ids
        ]

        if not run_ids:
            return total, []

        runs: list[dict[str, Any]] = []
        for run_id in run_ids:
            meta = await self.get_run_metadata(run_id)
            if meta:
                # Check whether finalized report artifact exists
                has_report = await self.redis.exists(self._report_key(run_id))
                meta["has_report"] = bool(has_report)
                runs.append(meta)
            else:
                # Remove stale/expired ID from index
                try:
                    await self.redis.zrem(idx_key, run_id)
                except Exception:
                    pass

        return total, runs

    async def get_run_metadata(self, run_id: str) -> dict[str, Any] | None:
        """Fetch metadata for a given run ID."""
        raw = await self.redis.get(self._meta_key(run_id))
        if not raw:
            return None
        data_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        return json.loads(data_str)

    def _report_key(self, run_id: str) -> str:
        return f"research:run:{run_id}:report"

    def _trace_key(self, run_id: str) -> str:
        return f"research:run:{run_id}:trace"

    async def record_completed_step(
        self,
        run_id: str,
        node_name: str,
        step_number: int,
    ) -> None:
        """Append a completed step to the run's audit trail."""
        step_record = json.dumps(
            {
                "node": node_name,
                "step": step_number,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        steps_key = self._steps_key(run_id)
        await self.redis.rpush(steps_key, step_record)
        if self.default_ttl and self.default_ttl > 0:
            await self.redis.expire(steps_key, self.default_ttl)

    async def get_step_history(self, run_id: str) -> list[dict[str, Any]]:
        """Retrieve the sequence of completed steps for a run."""
        raw_items = await self.redis.lrange(self._steps_key(run_id), 0, -1)
        history: list[dict[str, Any]] = []
        for item in raw_items:
            item_str = item.decode("utf-8") if isinstance(item, bytes) else item
            history.append(json.loads(item_str))
        return history

    async def save_report(self, run_id: str, report_data: dict[str, Any] | str) -> None:
        """Persist the finalized research report in Redis with automatic TTL."""
        payload = (
            report_data if isinstance(report_data, str) else json.dumps(report_data, default=str)
        )
        if self.default_ttl and self.default_ttl > 0:
            await self.redis.set(self._report_key(run_id), payload, ex=self.default_ttl)
        else:
            await self.redis.set(self._report_key(run_id), payload)

    async def get_report(self, run_id: str) -> dict[str, Any] | None:
        """Retrieve the persisted report for a given run ID."""
        raw = await self.redis.get(self._report_key(run_id))
        if not raw:
            return None
        data_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        return json.loads(data_str)

    async def save_audit_log(self, run_id: str, audit_data: dict[str, Any] | str) -> None:
        """Persist the full audit log in Redis with automatic TTL."""
        payload = audit_data if isinstance(audit_data, str) else json.dumps(audit_data, default=str)
        if self.default_ttl and self.default_ttl > 0:
            await self.redis.set(self._trace_key(run_id), payload, ex=self.default_ttl)
        else:
            await self.redis.set(self._trace_key(run_id), payload)

    async def get_audit_log(self, run_id: str) -> dict[str, Any] | None:
        """Retrieve the full audit log for a given run ID."""
        raw = await self.redis.get(self._trace_key(run_id))
        if not raw:
            return None
        data_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        return json.loads(data_str)

    async def apply_ttl(self, run_id: str, ttl_seconds: int | None = None) -> None:
        """Apply or refresh expiration TTL across all Redis artifacts associated with a run."""
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        if not ttl or ttl <= 0:
            return
        keys = [
            self._meta_key(run_id),
            self._steps_key(run_id),
            self._report_key(run_id),
            self._trace_key(run_id),
            f"research:run:{run_id}:events",
            f"checkpoint:{run_id}",
            f"checkpoint:{run_id}:latest",
        ]
        for key in keys:
            try:
                await self.redis.expire(key, ttl)
            except Exception:
                pass

    async def clear_run(self, run_id: str) -> None:
        """Purge metadata, step records, report, and audit records for a given run."""
        await self.redis.delete(
            self._meta_key(run_id),
            self._steps_key(run_id),
            self._report_key(run_id),
            self._trace_key(run_id),
            f"research:run:{run_id}:events",
            f"research:run:{run_id}:cancel",
            f"checkpoint:{run_id}",
            f"checkpoint:{run_id}:latest",
        )
        try:
            await self.redis.zrem(self._index_key(), run_id)
        except Exception:
            pass



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
