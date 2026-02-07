"""
In-memory cron job store with persistence hooks.

Stores cron jobs and their state. For persistence, serializes
to/from dicts that can be saved to SQLite or config.
"""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .types import CronJob, CronSchedule, ScheduleKind

logger = logging.getLogger(__name__)


class CronStore:
    """In-memory store for cron jobs."""

    def __init__(self):
        self._jobs: dict[str, CronJob] = {}

    def add(self, job: CronJob) -> CronJob:
        """Add a cron job."""
        if not job.id:
            job.id = str(uuid4())[:8]
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> CronJob | None:
        """Get a job by ID."""
        return self._jobs.get(job_id)

    def list_all(self, enabled_only: bool = False) -> list[CronJob]:
        """List all jobs."""
        jobs = list(self._jobs.values())
        if enabled_only:
            jobs = [j for j in jobs if j.enabled]
        return jobs

    def update(self, job_id: str, **kwargs) -> CronJob | None:
        """Update a job's fields."""
        job = self._jobs.get(job_id)
        if not job:
            return None
        for key, value in kwargs.items():
            if hasattr(job, key):
                setattr(job, key, value)
        return job

    def delete(self, job_id: str) -> bool:
        """Delete a job."""
        return self._jobs.pop(job_id, None) is not None

    def mark_run(
        self,
        job_id: str,
        success: bool = True,
        error: str | None = None,
        next_run: datetime | None = None,
    ) -> None:
        """Record that a job was executed."""
        job = self._jobs.get(job_id)
        if job:
            job.last_run = datetime.now(UTC)
            job.run_count += 1
            job.last_error = error if not success else None
            if next_run:
                job.next_run = next_run

    def to_dicts(self) -> list[dict[str, Any]]:
        """Serialize all jobs for persistence."""
        return [j.model_dump(mode="json") for j in self._jobs.values()]

    def load_dicts(self, data: list[dict[str, Any]]) -> int:
        """Load jobs from serialized dicts."""
        count = 0
        for d in data:
            try:
                job = CronJob(**d)
                self._jobs[job.id] = job
                count += 1
            except Exception as e:
                logger.warning("Failed to load cron job: %s", e)
        return count
