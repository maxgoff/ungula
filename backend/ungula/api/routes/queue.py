"""
Queue API routes.

Submit, list, cancel, and manage queued jobs.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...auth import get_current_user
from ...storage.base import User

logger = logging.getLogger(__name__)

router = APIRouter()


class SubmitJobRequest(BaseModel):
    """Request to submit a job."""

    type: str = Field(..., max_length=50)
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=0, ge=-100, le=100)
    max_retries: int = Field(default=3, ge=0, le=10)


def _get_queue_manager(request: Request):
    """Get the queue manager from app state."""
    qm = getattr(request.app.state, "queue_manager", None)
    if qm is None:
        raise HTTPException(status_code=503, detail="Queue manager not initialized")
    return qm


@router.post("/submit")
async def submit_job(
    body: SubmitJobRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Submit a new job to the queue."""
    qm = _get_queue_manager(request)
    job = await qm.submit(
        job_type=body.type,
        payload=body.payload,
        priority=body.priority,
        max_retries=body.max_retries,
    )
    return job.to_dict()


@router.get("/jobs")
async def list_jobs(
    request: Request,
    status: str | None = None,
    type: str | None = None,
    limit: int = 50,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List jobs with optional filters."""
    qm = _get_queue_manager(request)
    jobs = await qm.list_jobs(status=status, job_type=type, limit=min(limit, 200))
    return {
        "jobs": [j.to_dict() for j in jobs],
        "count": len(jobs),
    }


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get a job by ID."""
    qm = _get_queue_manager(request)
    job = await qm.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@router.delete("/jobs/{job_id}")
async def cancel_job(
    job_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Cancel a pending job."""
    qm = _get_queue_manager(request)
    if not await qm.cancel(job_id):
        raise HTTPException(status_code=400, detail="Job not found or not in pending state")
    return {"status": "cancelled", "job_id": job_id}


@router.post("/cleanup")
async def cleanup_jobs(
    request: Request,
    max_age_days: int = 7,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Remove old completed/failed jobs."""
    qm = _get_queue_manager(request)
    removed = await qm.cleanup(max_age_days=max_age_days)
    return {"removed": removed}


@router.get("/status")
async def queue_status(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get queue status."""
    qm = _get_queue_manager(request)
    return await qm.status()
