"""
Queue Manager.

High-level interface for the task queue. Tries Redis, falls back to in-memory.
"""

import logging
from typing import Any

from .backend import QueueBackend
from .memory_backend import InMemoryBackend
from .types import Job, JobStatus, JobType
from .worker import QueueWorker

logger = logging.getLogger(__name__)


class QueueManager:
    """
    Manages the task queue lifecycle.

    Tries Redis backend first, falls back to in-memory.
    Provides submit/get/cancel/status interface.
    """

    def __init__(
        self,
        redis_url: str | None = None,
        redis_config: Any = None,
        concurrency: int = 3,
        poll_interval: float = 2.0,
    ):
        self.redis_url = redis_url
        self.redis_config = redis_config
        self.concurrency = concurrency
        self.poll_interval = poll_interval
        self.backend: QueueBackend | None = None
        self.worker: QueueWorker | None = None
        self._backend_type = "none"

    async def initialize(self) -> str:
        """Initialize backend. Returns backend type name."""
        # Try Redis first
        if self.redis_config or self.redis_url:
            try:
                backend = await self._try_redis()
                if backend:
                    self.backend = backend
                    self._backend_type = "redis"
                    logger.info("Queue using Redis backend")
            except Exception as e:
                logger.warning("Redis unavailable, falling back to memory: %s", e)

        # Fallback to in-memory
        if self.backend is None:
            self.backend = InMemoryBackend()
            self._backend_type = "memory"
            logger.info("Queue using in-memory backend")

        # Create worker
        self.worker = QueueWorker(
            backend=self.backend,
            concurrency=self.concurrency,
            poll_interval=self.poll_interval,
        )

        return self._backend_type

    async def _try_redis(self) -> QueueBackend | None:
        """Attempt to connect to Redis."""
        try:
            import redis.asyncio as aioredis
        except ImportError:
            logger.debug("redis package not installed")
            return None

        try:
            if self.redis_url:
                client = aioredis.from_url(self.redis_url)
            elif self.redis_config:
                client = aioredis.Redis(
                    host=self.redis_config.host,
                    port=self.redis_config.port,
                    db=self.redis_config.db,
                    password=self.redis_config.password,
                )
            else:
                return None

            if not await client.ping():
                return None

            from .redis_backend import RedisBackend
            return RedisBackend(client)

        except Exception as e:
            logger.debug("Redis connection failed: %s", e)
            return None

    async def start_worker(self) -> None:
        """Start the background worker."""
        if self.worker:
            await self.worker.start()

    async def stop_worker(self) -> None:
        """Stop the background worker."""
        if self.worker:
            await self.worker.stop()

    def register_handler(self, job_type: str, handler) -> None:
        """Register a job handler."""
        if self.worker:
            self.worker.register_handler(job_type, handler)

    async def submit(
        self,
        job_type: str,
        payload: dict[str, Any],
        priority: int = 0,
        max_retries: int = 3,
    ) -> Job:
        """Submit a new job to the queue."""
        if not self.backend:
            raise RuntimeError("Queue not initialized")

        job = Job(
            type=job_type,
            payload=payload,
            priority=priority,
            max_retries=max_retries,
        )
        await self.backend.enqueue(job)
        return job

    async def get_job(self, job_id: str) -> Job | None:
        """Get a job by ID."""
        if not self.backend:
            return None
        return await self.backend.get(job_id)

    async def list_jobs(
        self,
        status: str | None = None,
        job_type: str | None = None,
        limit: int = 50,
    ) -> list[Job]:
        """List jobs with optional filters."""
        if not self.backend:
            return []
        return await self.backend.list_jobs(status=status, job_type=job_type, limit=limit)

    async def cancel(self, job_id: str) -> bool:
        """Cancel a pending job."""
        if not self.backend:
            return False

        job = await self.backend.get(job_id)
        if not job or job.status != JobStatus.PENDING:
            return False

        job.status = JobStatus.CANCELLED
        await self.backend.update(job)
        return True

    async def cleanup(self, max_age_days: int = 7) -> int:
        """Remove old completed/failed jobs."""
        if not self.backend:
            return 0
        return await self.backend.cleanup(max_age_days=max_age_days)

    async def status(self) -> dict[str, Any]:
        """Get queue status."""
        result: dict[str, Any] = {
            "backend": self._backend_type,
            "worker_running": self.worker.is_running if self.worker else False,
        }

        if self.backend:
            result["backend_available"] = await self.backend.ping()
            jobs = await self.backend.list_jobs(limit=1000)
            status_counts: dict[str, int] = {}
            for job in jobs:
                status_counts[job.status] = status_counts.get(job.status, 0) + 1
            result["jobs"] = status_counts
            result["total_jobs"] = len(jobs)

        return result
