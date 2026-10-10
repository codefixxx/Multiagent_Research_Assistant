"""Event broadcaster and subscription manager for real-time streaming."""

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from src.core.logger import logger


class EventBroadcaster:
    """In-memory pub/sub broker distributing lifecycle events to SSE listeners."""

    def __init__(self) -> None:
        # Maps run_id -> set of asyncio.Queue instances
        self._subscribers: dict[str, set[asyncio.Queue[str]]] = {}
        # Stores recent event history per run_id for replay upon late client connect
        self._history: dict[str, list[str]] = {}
        self._lock = asyncio.Lock()

    def format_sse(self, event: str, data: dict[str, Any]) -> str:
        """Format a payload according to the W3C Server-Sent Events specification."""
        payload_json = json.dumps(data)
        return f"event: {event}\ndata: {payload_json}\n\n"

    async def broadcast(self, run_id: str, event: str, data: dict[str, Any]) -> None:
        """Publish an event to all active subscribers listening to this run_id."""
        envelope = {
            "event": event,
            "run_id": run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": data,
            **data,
        }
        sse_message = self.format_sse(event, envelope)

        async with self._lock:
            # Store in history
            if run_id not in self._history:
                self._history[run_id] = []
            self._history[run_id].append(sse_message)

            listeners = self._subscribers.get(run_id, set()).copy()

        for queue in listeners:
            try:
                queue.put_nowait(sse_message)
            except asyncio.QueueFull:
                logger.warning("Dropped SSE event due to full queue", run_id=run_id, event=event)

    async def subscribe(
        self,
        run_id: str,
        heartbeat_interval: float = 15.0,
    ) -> AsyncGenerator[str, None]:
        """Subscribe to a run's event stream, yielding SSE formatted strings.

        Replays past events, streams live events, and yields keep-alive pings.
        """
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)

        async with self._lock:
            if run_id not in self._subscribers:
                self._subscribers[run_id] = set()
            self._subscribers[run_id].add(queue)

            # Replay historical events
            past_events = list(self._history.get(run_id, []))

        # First yield past events
        for past_event in past_events:
            yield past_event

        # Check if the run has already finished
        if past_events and any(
            '"event": "job_completed"' in pe or '"event": "job_failed"' in pe for pe in past_events
        ):
            # Already completed; unsubscribe and exit
            async with self._lock:
                if run_id in self._subscribers:
                    self._subscribers[run_id].discard(queue)
            return

        try:
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
                    yield message
                    # If this message was termination, stop stream
                    if (
                        "event: job_completed" in message
                        or "event: job_failed" in message
                        or "event: budget_exceeded" in message
                    ):
                        break
                except TimeoutError:
                    # Send keep-alive comment
                    yield ": ping keep-alive\n\n"
        finally:
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


# Singleton event broadcaster instance
broadcaster = EventBroadcaster()
