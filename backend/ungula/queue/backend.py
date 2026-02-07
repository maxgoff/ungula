"""
Abstract queue backend interface.
"""

from abc import ABC, abstractmethod
from typing import Any

from .types import Job


class QueueBackend(ABC):
    """Abstract base class for queue backends."""

    @abstractmethod
    async def enqueue(self, job: Job) -> str:
        """Add a job to the queue. Returns job ID."""
        ...

    @abstractmethod
    async def dequeue(self) -> Job | None:
        """Get the next job to process (highest priority first). Returns None if empty."""
        ...

    @abstractmethod
    async def get(self, job_id: str) -> Job | None:
        """Get a job by ID."""
        ...

    @abstractmethod
    async def update(self, job: Job) -> None:
        """Update a job's state."""
        ...

    @abstractmethod
    async def list_jobs(
        self,
        status: str | None = None,
        job_type: str | None = None,
        limit: int = 50,
    ) -> list[Job]:
        """List jobs with optional filters."""
        ...

    @abstractmethod
    async def delete(self, job_id: str) -> bool:
        """Delete a job. Returns True if found."""
        ...

    @abstractmethod
    async def cleanup(self, max_age_days: int = 7) -> int:
        """Remove old completed/failed jobs. Returns count removed."""
        ...

    @abstractmethod
    async def ping(self) -> bool:
        """Check if the backend is available."""
        ...
