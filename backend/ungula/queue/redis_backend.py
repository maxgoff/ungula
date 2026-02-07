"""
Redis queue backend.

Uses sorted sets for priority queue and hashes for job data.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from .backend import QueueBackend
from .types import Job, JobStatus

logger = logging.getLogger(__name__)

# 7-day TTL for job data in Redis
JOB_TTL_SECONDS = 7 * 24 * 60 * 60

QUEUE_KEY = "ungula:queue:pending"
JOB_PREFIX = "ungula:job:"


def _serialize_job(job: Job) -> str:
    """Serialize a Job to JSON string."""
    return json.dumps(job.to_dict(), default=str)


def _deserialize_job(data: str) -> Job:
    """Deserialize a Job from JSON string."""
    d = json.loads(data)
    # Convert ISO strings back to datetimes
    for field in ("created_at", "started_at", "completed_at"):
        if d.get(field):
            d[field] = datetime.fromisoformat(d[field])
    return Job(**d)


class RedisBackend(QueueBackend):
    """Redis-based queue backend using sorted sets for priority."""

    def __init__(self, redis_client: Any):
        self._redis = redis_client

    async def enqueue(self, job: Job) -> str:
        pipe = self._redis.pipeline()
        # Store job data as a hash value
        pipe.set(f"{JOB_PREFIX}{job.id}", _serialize_job(job), ex=JOB_TTL_SECONDS)
        # Add to priority queue (score = -priority so higher priority = lower score = first out)
        pipe.zadd(QUEUE_KEY, {job.id: -job.priority})
        await pipe.execute()
        return job.id

    async def dequeue(self) -> Job | None:
        # Pop lowest score (highest priority) from sorted set
        results = await self._redis.zpopmin(QUEUE_KEY, count=1)
        if not results:
            return None

        job_id, _ = results[0]
        if isinstance(job_id, bytes):
            job_id = job_id.decode()

        return await self.get(job_id)

    async def get(self, job_id: str) -> Job | None:
        data = await self._redis.get(f"{JOB_PREFIX}{job_id}")
        if data is None:
            return None
        if isinstance(data, bytes):
            data = data.decode()
        return _deserialize_job(data)

    async def update(self, job: Job) -> None:
        await self._redis.set(
            f"{JOB_PREFIX}{job.id}",
            _serialize_job(job),
            ex=JOB_TTL_SECONDS,
        )

    async def list_jobs(
        self,
        status: str | None = None,
        job_type: str | None = None,
        limit: int = 50,
    ) -> list[Job]:
        # Scan for job keys
        jobs = []
        async for key in self._redis.scan_iter(f"{JOB_PREFIX}*", count=200):
            if len(jobs) >= limit * 3:  # Pre-filter limit
                break
            data = await self._redis.get(key)
            if data is None:
                continue
            if isinstance(data, bytes):
                data = data.decode()
            try:
                job = _deserialize_job(data)
                if status and job.status != status:
                    continue
                if job_type and job.type != job_type:
                    continue
                jobs.append(job)
            except Exception:
                continue

        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    async def delete(self, job_id: str) -> bool:
        # Remove from both queue and storage
        pipe = self._redis.pipeline()
        pipe.delete(f"{JOB_PREFIX}{job_id}")
        pipe.zrem(QUEUE_KEY, job_id)
        results = await pipe.execute()
        return results[0] > 0

    async def cleanup(self, max_age_days: int = 7) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        terminal = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
        removed = 0

        async for key in self._redis.scan_iter(f"{JOB_PREFIX}*", count=200):
            data = await self._redis.get(key)
            if data is None:
                continue
            if isinstance(data, bytes):
                data = data.decode()
            try:
                job = _deserialize_job(data)
                if job.status in terminal and job.created_at < cutoff:
                    await self._redis.delete(key)
                    removed += 1
            except Exception:
                continue

        return removed

    async def ping(self) -> bool:
        try:
            return await self._redis.ping()
        except Exception:
            return False
