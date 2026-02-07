"""
Cron job type definitions.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ScheduleKind(str, Enum):
    """Types of schedule definitions."""

    AT = "at"       # Run at a specific time (e.g., "14:30")
    EVERY = "every"  # Run every N minutes/hours
    CRON = "cron"   # Standard cron expression


class CronSchedule(BaseModel):
    """Schedule definition for a cron job."""

    kind: ScheduleKind
    value: str = Field(
        description=(
            "For 'at': time string like '14:30'. "
            "For 'every': interval like '30m', '2h', '1d'. "
            "For 'cron': cron expression like '*/5 * * * *'."
        )
    )


class CronJob(BaseModel):
    """A scheduled job."""

    id: str
    name: str
    schedule: CronSchedule
    action: str = Field(description="Action type: 'agent', 'command', 'webhook'")
    action_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific config (e.g., agent_id, command, url)",
    )
    enabled: bool = True
    last_run: datetime | None = None
    next_run: datetime | None = None
    run_count: int = 0
    last_error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
