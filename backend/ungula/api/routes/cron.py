"""
Cron scheduler API routes.

CRUD for scheduled jobs plus run-now and status endpoints.
"""

import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...auth import get_current_user
from ...cron.types import CronJob, CronSchedule, ScheduleKind
from ...storage.base import User

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateJobRequest(BaseModel):
    """Request to create a cron job."""

    name: str = Field(..., max_length=200)
    schedule_kind: ScheduleKind
    schedule_value: str = Field(..., max_length=100)
    action: str = Field(..., max_length=50)
    action_config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class UpdateJobRequest(BaseModel):
    """Request to update a cron job."""

    name: str | None = None
    schedule_kind: ScheduleKind | None = None
    schedule_value: str | None = None
    enabled: bool | None = None
    action_config: dict[str, Any] | None = None


def _get_scheduler(request: Request):
    """Get the cron scheduler from app state."""
    scheduler = getattr(request.app.state, "cron_scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Cron scheduler not initialized")
    return scheduler


@router.get("/jobs")
async def list_jobs(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List all cron jobs."""
    scheduler = _get_scheduler(request)
    jobs = scheduler.store.list_all()
    return {
        "jobs": [j.model_dump(mode="json") for j in jobs],
        "count": len(jobs),
    }


@router.post("/jobs")
async def create_job(
    body: CreateJobRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a new cron job."""
    scheduler = _get_scheduler(request)

    from ...cron.scheduler import compute_next_run

    job = CronJob(
        id=str(uuid4())[:8],
        name=body.name,
        schedule=CronSchedule(kind=body.schedule_kind, value=body.schedule_value),
        action=body.action,
        action_config=body.action_config,
        enabled=body.enabled,
    )
    job.next_run = compute_next_run(job)

    scheduler.store.add(job)
    return job.model_dump(mode="json")


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get a cron job by ID."""
    scheduler = _get_scheduler(request)
    job = scheduler.store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.model_dump(mode="json")


@router.put("/jobs/{job_id}")
async def update_job(
    job_id: str,
    body: UpdateJobRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Update a cron job."""
    scheduler = _get_scheduler(request)
    job = scheduler.store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    updates = body.model_dump(exclude_none=True)

    # Handle schedule updates
    if "schedule_kind" in updates or "schedule_value" in updates:
        kind = updates.pop("schedule_kind", job.schedule.kind)
        value = updates.pop("schedule_value", job.schedule.value)
        updates["schedule"] = CronSchedule(kind=kind, value=value)

    updated = scheduler.store.update(job_id, **updates)
    if updated:
        from ...cron.scheduler import compute_next_run

        updated.next_run = compute_next_run(updated)

    return updated.model_dump(mode="json") if updated else {}


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete a cron job."""
    scheduler = _get_scheduler(request)
    if not scheduler.store.delete(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "deleted"}


@router.post("/jobs/{job_id}/run")
async def run_job_now(
    job_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Execute a cron job immediately."""
    scheduler = _get_scheduler(request)
    success = await scheduler.run_now(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "executed", "job_id": job_id}


@router.get("/status")
async def scheduler_status(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get scheduler status."""
    scheduler = _get_scheduler(request)
    jobs = scheduler.store.list_all()
    return {
        "running": scheduler._running,
        "total_jobs": len(jobs),
        "enabled_jobs": len([j for j in jobs if j.enabled]),
        "tick_interval": scheduler.tick_interval,
    }
