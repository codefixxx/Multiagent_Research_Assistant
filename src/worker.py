"""Dedicated distributed worker daemon consuming research jobs from Redis queue."""

import argparse
import asyncio
import os
import signal
import uuid
from typing import Any

from src.api.events import broadcaster
from src.api.job_runner import ResearchJobService
from src.config import settings
from src.core.exceptions import classify_error
from src.core.logger import logger
from src.persistence.queue import RedisJobQueue
from src.persistence.redis_saver import get_redis_client
from src.schemas.api import ResearchRequest


class ResearchWorker:
    """Consumes research tasks from Redis queue and runs the LangGraph multi-agent research pipeline."""

    def __init__(
        self,
        worker_id: str | None = None,
        concurrency: int | None = None,
        job_service: ResearchJobService | None = None,
        queue: RedisJobQueue | None = None,
    ) -> None:
        self.worker_id = worker_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.concurrency = max(1, concurrency or settings.WORKER_CONCURRENCY)
        self.semaphore = asyncio.Semaphore(self.concurrency)
        self.job_service = job_service
        self.queue = queue
        self._running = False
        self._active_tasks: set[asyncio.Task[Any]] = set()
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        """Initialize Redis connection, job service, queue, and event broadcaster."""
        client = await get_redis_client()
        if self.queue is None:
            self.queue = RedisJobQueue(client)
        if self.job_service is None:
            self.job_service = ResearchJobService(queue=self.queue)
            await self.job_service.initialize()
        await broadcaster.initialize(client)

    async def start(self) -> None:
        """Start worker polling loop."""
        await self.initialize()
        self._running = True
        logger.info(
            "Research worker daemon started",
            worker_id=self.worker_id,
            concurrency=self.concurrency,
        )

        # Start periodic worker heartbeat in Redis
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        try:
            while self._running:
                # Wait for slot in concurrency semaphore
                await self.semaphore.acquire()
                if not self._running:
                    self.semaphore.release()
                    break

                try:
                    assert self.queue is not None
                    job_data = await self.queue.dequeue(timeout=1.5)
                except Exception as e:
                    self.semaphore.release()
                    if self._running:
                        logger.error("Error dequeueing from Redis queue", error=str(e))
                        await asyncio.sleep(1.0)
                    continue

                if not job_data:
                    # Timeout with empty queue: release semaphore and continue polling
                    self.semaphore.release()
                    continue

                # Process job in background task bounded by semaphore
                task = asyncio.create_task(self._process_job_wrapper(job_data))
                self._active_tasks.add(task)
                task.add_done_callback(self._active_tasks.discard)

        finally:
            await self.shutdown()

    async def _process_job_wrapper(self, job_data: dict[str, Any]) -> None:
        """Wrapper ensuring concurrency semaphore release upon task finish."""
        try:
            await self.process_job(job_data)
        finally:
            self.semaphore.release()

    async def process_job(self, job_data: dict[str, Any]) -> None:
        """Execute a single dequeued research job."""
        run_id = job_data.get("run_id")
        req_dict = job_data.get("request", {})
        if not run_id:
            logger.warning("Received invalid job data missing run_id", job_data=job_data)
            return

        logger.info("Worker picked up research job from queue", worker_id=self.worker_id, run_id=run_id)

        try:
            request = ResearchRequest.model_validate(req_dict)
            assert self.job_service is not None
            # Execute the research graph with all telemetry, persistence, and event emissions
            llm_to_use = getattr(self.job_service, "default_llm", None)
            await self.job_service._execute_job(run_id=run_id, request=request, llm=llm_to_use)
            logger.info("Worker successfully completed research job", worker_id=self.worker_id, run_id=run_id)
        except Exception as e:
            app_err = classify_error(e)
            logger.error(
                "Worker failed processing job",
                worker_id=self.worker_id,
                run_id=run_id,
                code=app_err.code,
                error=app_err.message,
                suggestion=app_err.suggestion,
            )
            if self.job_service and self.job_service.run_manager:
                try:
                    await self.job_service.run_manager.update_run_status(
                        run_id=run_id,
                        status="failed",
                        error_message=app_err.message,
                        error_code=app_err.code,
                        error_suggestion=app_err.suggestion,
                        error_details=app_err.details,
                    )
                    await self.job_service.broadcaster.broadcast(
                        run_id=run_id,
                        event="job_failed",
                        data={
                            "status": "failed",
                            "error": app_err.message,
                            "code": app_err.code,
                            "suggestion": app_err.suggestion,
                            "details": app_err.details,
                        },
                    )
                except Exception:
                    pass

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to Redis registering worker availability."""
        while self._running:
            try:
                if self.queue:
                    await self.queue.register_worker(
                        worker_id=self.worker_id,
                        metadata={
                            "concurrency": self.concurrency,
                            "active_jobs": len(self._active_tasks),
                            "pid": os.getpid(),
                        },
                        ttl=15,
                    )
            except Exception as e:
                logger.debug("Failed sending worker heartbeat", error=str(e))
            await asyncio.sleep(5.0)

    async def stop(self) -> None:
        """Signal the worker loop to stop gracefully."""
        self._running = False

    async def shutdown(self) -> None:
        """Gracefully drain running jobs and deregister worker."""
        self._running = False
        logger.info("Shutting down research worker...", worker_id=self.worker_id)
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()

        if self.queue:
            try:
                await self.queue.deregister_worker(self.worker_id)
            except Exception:
                pass

        if self._active_tasks:
            logger.info(f"Waiting for {len(self._active_tasks)} active jobs to complete...")
            await asyncio.gather(*self._active_tasks, return_exceptions=True)

        logger.info("Research worker stopped cleanly", worker_id=self.worker_id)


def run_worker(concurrency: int | None = None, worker_id: str | None = None) -> None:
    """Synchronous launcher entrypoint for CLI execution."""
    worker = ResearchWorker(concurrency=concurrency, worker_id=worker_id)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _handle_exit() -> None:
        logger.info("Termination signal received; stopping worker...")
        loop.create_task(worker.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_exit)
        except (NotImplementedError, AttributeError):
            pass

    try:
        loop.run_until_complete(worker.start())
    except KeyboardInterrupt:
        loop.run_until_complete(worker.stop())
    finally:
        loop.close()


def main() -> None:
    """CLI entrypoint parsing options and starting worker daemon."""
    parser = argparse.ArgumentParser(description="Multi-Agent Research Assistant Decoupled Worker")
    parser.add_argument("--concurrency", type=int, default=None, help="Worker concurrency limit")
    parser.add_argument("--worker-id", type=str, default=None, help="Custom identifier for this worker node")
    args = parser.parse_args()

    run_worker(concurrency=args.concurrency, worker_id=args.worker_id)


if __name__ == "__main__":
    main()
