"""
Cron scheduler.

Asyncio-based scheduler that checks for due jobs and executes them.
Supports at/every/cron schedule kinds.
"""

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Awaitable

from .store import CronStore
from .types import CronJob, ScheduleKind

logger = logging.getLogger(__name__)


def _parse_interval(value: str) -> timedelta | None:
    """Parse an interval string like '30m', '2h', '1d' to timedelta."""
    match = re.match(r"^(\d+)\s*([smhd])$", value.strip().lower())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "s":
        return timedelta(seconds=amount)
    elif unit == "m":
        return timedelta(minutes=amount)
    elif unit == "h":
        return timedelta(hours=amount)
    elif unit == "d":
        return timedelta(days=amount)
    return None


def _next_cron_run(cron_expr: str, after: datetime) -> datetime | None:
    """Calculate the next run time for a cron expression."""
    try:
        from croniter import croniter

        cron = croniter(cron_expr, after)
        return cron.get_next(datetime).replace(tzinfo=UTC)
    except ImportError:
        logger.warning("croniter not installed, cron expressions not supported")
        return None
    except Exception as e:
        logger.error("Invalid cron expression '%s': %s", cron_expr, e)
        return None


def _next_at_run(time_str: str, after: datetime) -> datetime:
    """Calculate the next daily run for a time like '14:30'."""
    parts = time_str.strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0

    candidate = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= after:
        candidate += timedelta(days=1)
    return candidate


def compute_next_run(job: CronJob) -> datetime | None:
    """Compute the next run time for a job."""
    now = datetime.now(UTC)

    if job.schedule.kind == ScheduleKind.EVERY:
        interval = _parse_interval(job.schedule.value)
        if not interval:
            return None
        base = job.last_run or now
        return base + interval

    elif job.schedule.kind == ScheduleKind.AT:
        return _next_at_run(job.schedule.value, now)

    elif job.schedule.kind == ScheduleKind.CRON:
        return _next_cron_run(job.schedule.value, now)

    return None


# Type for job execution callback
JobExecutor = Callable[[CronJob], Awaitable[None]]


class CronScheduler:
    """
    Asyncio-based cron scheduler.

    Runs as a background task, checking for due jobs every tick_interval.
    """

    def __init__(
        self,
        store: CronStore | None = None,
        executor: JobExecutor | None = None,
        tick_interval: float = 30.0,
        event_bus: Any = None,
        queue_manager: Any = None,
    ):
        self.store = store or CronStore()
        self.executor = executor
        self.tick_interval = tick_interval
        self.event_bus = event_bus
        self.queue_manager = queue_manager
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            return

        # Compute initial next_run for all jobs
        for job in self.store.list_all(enabled_only=True):
            if job.next_run is None:
                job.next_run = compute_next_run(job)

        self._running = True
        self._task = asyncio.create_task(self._tick_loop())
        logger.info("Cron scheduler started (tick=%.0fs)", self.tick_interval)

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Cron scheduler stopped")

    async def run_now(self, job_id: str) -> bool:
        """Execute a job immediately."""
        job = self.store.get(job_id)
        if not job:
            return False
        await self._execute_job(job)
        return True

    async def _tick_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                await self._check_due_jobs()
            except Exception as e:
                logger.error("Scheduler tick error: %s", e)
            await asyncio.sleep(self.tick_interval)

    async def _check_due_jobs(self) -> None:
        """Check for and execute due jobs."""
        now = datetime.now(UTC)

        for job in self.store.list_all(enabled_only=True):
            if job.next_run and job.next_run <= now:
                await self._execute_job(job)

    async def _execute_job(self, job: CronJob) -> None:
        """Execute a single cron job."""
        logger.info("Executing cron job: %s (%s)", job.name, job.id)

        try:
            if self.executor:
                await self.executor(job)

            next_run = compute_next_run(job)
            self.store.mark_run(job.id, success=True, next_run=next_run)
            logger.info("Cron job %s completed, next run: %s", job.id, next_run)

            # Emit cron.fired event
            if self.event_bus:
                try:
                    from ..events.types import Event

                    self.event_bus.emit(Event(
                        type="cron.fired",
                        data={
                            "job_id": job.id,
                            "job_name": job.name,
                            "action": job.action,
                        },
                    ))
                except Exception:
                    pass

        except Exception as e:
            logger.error("Cron job %s failed: %s", job.id, e)
            next_run = compute_next_run(job)
            self.store.mark_run(job.id, success=False, error=str(e), next_run=next_run)
