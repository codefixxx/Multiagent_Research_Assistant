"""Event broadcaster and subscription manager for real-time streaming with Redis Pub/Sub."""

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from src.config import settings
from src.core.logger import logger

EVENT_STREAM_KEY = "research:run:{run_id}:events"
EVENT_CHANNEL = "research:events:{run_id}"


class EventBroadcaster:
    """Pub/sub broker distributing lifecycle events to SSE listeners with Redis and in-memory support."""

    def __init__(self, redis_client: Any = None) -> None:
        self.redis = redis_client
        # Maps run_id -> set of asyncio.Queue instances for local in-process delivery
        self._subscribers: dict[str, set[asyncio.Queue[str]]] = {}
        # Stores recent event history per run_id for replay upon late client connect
        self._history: dict[str, list[str]] = {}
        self._lock = asyncio.Lock()

    async def initialize(self, redis_client: Any = None) -> None:
        """Bind Redis client for cross-process event broadcasting and history persistence."""
        if redis_client is not None:
            self.redis = redis_client

    def format_sse(self, event: str, data: dict[str, Any]) -> str:
        """Format a payload according to the W3C Server-Sent Events specification."""
        payload_json = json.dumps(data)
        return f"event: {event}\ndata: {payload_json}\n\n"

    async def broadcast(self, run_id: str, event: str, data: dict[str, Any]) -> None:
        """Publish an event to active subscribers and persist in Redis event history."""
        envelope = {
            "event": event,
            "run_id": run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": data,
            **data,
        }
        sse_message = self.format_sse(event, envelope)

        async with self._lock:
            # Store in local in-memory history
            if run_id not in self._history:
                self._history[run_id] = []
            self._history[run_id].append(sse_message)

            listeners = self._subscribers.get(run_id, set()).copy()

        # Local in-process delivery to any attached asyncio queues
        for queue in listeners:
            try:
                queue.put_nowait(sse_message)
            except asyncio.QueueFull:
                logger.warning("Dropped SSE event due to full queue", run_id=run_id, event=event)

        # Cross-process Redis distribution and persistent replay storage
        if self.redis is not None:
            try:
                stream_key = EVENT_STREAM_KEY.format(run_id=run_id)
                channel = EVENT_CHANNEL.format(run_id=run_id)
                # Store in Redis list for durable replay across server restarts
                await self.redis.rpush(stream_key, sse_message)
                retention = getattr(settings, "REPORT_RETENTION_SECONDS", 86400)
                if retention and retention > 0:
                    await self.redis.expire(stream_key, retention)
                # Publish on Redis channel for decoupled worker -> SSE distribution
                await self.redis.publish(channel, sse_message)
            except Exception as e:
                logger.debug("Redis broadcast failed; local delivery used", error=str(e), run_id=run_id)

    async def subscribe(
        self,
        run_id: str,
        heartbeat_interval: float = 15.0,
    ) -> AsyncGenerator[str, None]:
        """Subscribe to a run's event stream, yielding SSE formatted strings.

        Replays past events from Redis or memory, then streams live events via Redis Pub/Sub or local queue.
        """
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)

        async with self._lock:
            if run_id not in self._subscribers:
                self._subscribers[run_id] = set()
            self._subscribers[run_id].add(queue)

        pubsub: Any = None
        listener_gen: Any = None
        if self.redis is not None:
            try:
                pubsub = self.redis.pubsub()
                await pubsub.subscribe(EVENT_CHANNEL.format(run_id=run_id))
                listener_gen = pubsub.listen()
                # Consume subscribe acknowledgement
                await anext(listener_gen)
            except Exception as e:
                logger.debug("Failed opening Redis pubsub, falling back to local queue", error=str(e))
                if pubsub:
                    try:
                        await pubsub.aclose()
                    except Exception:
                        pass
                pubsub = None
                listener_gen = None

        # Replay historical events
        past_events: list[str] = []
        if self.redis is not None:
            try:
                stream_key = EVENT_STREAM_KEY.format(run_id=run_id)
                raw_items = await self.redis.lrange(stream_key, 0, -1)
                for item in raw_items:
                    past_events.append(item.decode("utf-8") if isinstance(item, bytes) else item)
            except Exception:
                pass

        if not past_events:
            async with self._lock:
                past_events = list(self._history.get(run_id, []))

        # First yield past events
        for past_event in past_events:
            yield past_event

        # Check if the run has already finished
        if past_events and any(
            '"event": "job_completed"' in pe
            or '"event": "job_failed"' in pe
            or '"event": "budget_exceeded"' in pe
            for pe in past_events
        ):
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(EVENT_CHANNEL.format(run_id=run_id))
                    await pubsub.aclose()
                except Exception:
                    pass
            async with self._lock:
                if run_id in self._subscribers:
                    self._subscribers[run_id].discard(queue)
            return

        # Stream live events
        try:
            if listener_gen is not None:
                while True:
                    try:
                        msg = await asyncio.wait_for(anext(listener_gen), timeout=heartbeat_interval)
                        if msg and msg.get("type") == "message":
                            raw_data = msg.get("data")
                            data_str = (
                                raw_data.decode("utf-8")
                                if isinstance(raw_data, bytes)
                                else str(raw_data)
                            )
                            yield data_str
                            if (
                                "event: job_completed" in data_str
                                or "event: job_failed" in data_str
                                or "event: budget_exceeded" in data_str
                            ):
                                break
                    except TimeoutError:
                        yield ": ping keep-alive\n\n"
            else:
                while True:
                    try:
                        message = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
                        yield message
                        if (
                            "event: job_completed" in message
                            or "event: job_failed" in message
                            or "event: budget_exceeded" in message
                        ):
                            break
                    except TimeoutError:
                        yield ": ping keep-alive\n\n"
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(EVENT_CHANNEL.format(run_id=run_id))
                    await pubsub.aclose()
                except Exception:
                    pass
            async with self._lock:
                if run_id in self._subscribers:
                    self._subscribers[run_id].discard(queue)
                    if not self._subscribers[run_id]:
                        del self._subscribers[run_id]

    async def clear_history(self, run_id: str) -> None:
        """Purge stored event history for a completed run."""
        async with self._lock:
            self._history.pop(run_id, None)
            self._subscribers.pop(run_id, None)
        if self.redis is not None:
            try:
                await self.redis.delete(EVENT_STREAM_KEY.format(run_id=run_id))
            except Exception:
                pass


# Singleton event broadcaster instance
broadcaster = EventBroadcaster()
