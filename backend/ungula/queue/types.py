"""
Queue job types and models.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class JobStatus(str, Enum):
    """Job lifecycle status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    """Known job types."""

    AGENT_RUN = "agent_run"
    TOOL_EXECUTE = "tool_execute"
    WEBHOOK_DISPATCH = "webhook_dispatch"
    CUSTOM = "custom"


@dataclass
class Job:
    """A queued job."""

    id: str = field(default_factory=lambda: str(uuid4()))
    type: str = JobType.CUSTOM
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = JobStatus.PENDING
    priority: int = 0  # Higher = higher priority
    result: dict[str, Any] | None = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "id": self.id,
            "type": self.type,
            "payload": self.payload,
            "status": self.status,
            "priority": self.priority,
            "result": self.result,
            "error": self.error,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
