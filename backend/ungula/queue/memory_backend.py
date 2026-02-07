"""
In-memory queue backend.

Used as fallback when Redis is not available.
"""

from collections import OrderedDict
from datetime import UTC, datetime, timedelta

from .backend import QueueBackend
from .types import Job, JobStatus


class InMemoryBackend(QueueBackend):
    """OrderedDict-based in-memory queue backend with priority sorting."""

    def __init__(self):
        self._jobs: OrderedDict[str, Job] = OrderedDict()

    async def enqueue(self, job: Job) -> str:
        self._jobs[job.id] = job
        return job.id

    async def dequeue(self) -> Job | None:
        """Get the highest-priority pending job."""
        pending = [
            j for j in self._jobs.values()
            if j.status == JobStatus.PENDING
        ]
        if not pending:
            return None

        # Sort by priority descending, then by creation time ascending
        pending.sort(key=lambda j: (-j.priority, j.created_at))
        return pending[0]

    async def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def update(self, job: Job) -> None:
        if job.id in self._jobs:
            self._jobs[job.id] = job

    async def list_jobs(
        self,
        status: str | None = None,
        job_type: str | None = None,
        limit: int = 50,
    ) -> list[Job]:
        jobs = list(self._jobs.values())

        if status:
            jobs = [j for j in jobs if j.status == status]
        if job_type:
            jobs = [j for j in jobs if j.type == job_type]

        # Most recent first
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    async def delete(self, job_id: str) -> bool:
        return self._jobs.pop(job_id, None) is not None

    async def cleanup(self, max_age_days: int = 7) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        terminal = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}

        to_remove = [
            jid for jid, job in self._jobs.items()
            if job.status in terminal and job.created_at < cutoff
        ]
        for jid in to_remove:
            del self._jobs[jid]
        return len(to_remove)

    async def ping(self) -> bool:
        return True
