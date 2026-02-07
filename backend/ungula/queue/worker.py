"""
Queue Worker.

Background asyncio task that polls the queue and processes jobs.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from .backend import QueueBackend
from .types import Job, JobStatus

logger = logging.getLogger(__name__)

# Type for job handlers
JobHandler = Callable[[Job], Awaitable[dict[str, Any] | None]]


class QueueWorker:
    """
    Background worker that polls the queue and processes jobs.

    Supports:
    - Handler registry per job type
    - Configurable concurrency via semaphore
    - Retry logic with max_retries
    """

    def __init__(
        self,
        backend: QueueBackend,
        concurrency: int = 3,
        poll_interval: float = 2.0,
    ):
        self.backend = backend
        self.concurrency = concurrency
        self.poll_interval = poll_interval
        self._handlers: dict[str, JobHandler] = {}
        self._semaphore = asyncio.Semaphore(concurrency)
        self._task: asyncio.Task | None = None
        self._running = False

    def register_handler(self, job_type: str, handler: JobHandler) -> None:
        """Register a handler for a job type."""
        self._handlers[job_type] = handler

    async def start(self) -> None:
        """Start the worker."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Queue worker started (concurrency=%d)", self.concurrency)

    async def stop(self) -> None:
        """Stop the worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Queue worker stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                job = await self.backend.dequeue()
                if job:
                    # Mark as running immediately to prevent re-dequeue
                    job.status = JobStatus.RUNNING
                    job.started_at = datetime.now(UTC)
                    await self.backend.update(job)
                    asyncio.create_task(self._process_with_semaphore(job))
                else:
                    await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Worker poll error: %s", e)
                await asyncio.sleep(self.poll_interval)

    async def _process_with_semaphore(self, job: Job) -> None:
        """Process a job with concurrency limiting."""
        async with self._semaphore:
            await self._process_job(job)

    async def _process_job(self, job: Job) -> None:
        """Process a single job."""
        handler = self._handlers.get(job.type)
        if not handler:
            logger.warning("No handler for job type: %s", job.type)
            job.status = JobStatus.FAILED
            job.error = f"No handler for job type: {job.type}"
            await self.backend.update(job)
            return

        try:
            result = await handler(job)
            job.status = JobStatus.COMPLETED
            job.result = result or {}
            job.completed_at = datetime.now(UTC)
            await self.backend.update(job)
            logger.info("Job %s completed", job.id)

        except Exception as e:
            job.retry_count += 1
            logger.error("Job %s failed (attempt %d): %s", job.id, job.retry_count, e)

            if job.retry_count < job.max_retries:
                # Re-enqueue for retry
                job.status = JobStatus.PENDING
                job.error = str(e)
                await self.backend.enqueue(job)
                logger.info("Job %s re-enqueued for retry", job.id)
            else:
                job.status = JobStatus.FAILED
                job.error = str(e)
                job.completed_at = datetime.now(UTC)
                await self.backend.update(job)
                logger.error("Job %s permanently failed after %d retries", job.id, job.max_retries)
