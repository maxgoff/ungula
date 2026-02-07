"""
Security audit API routes.

Provides endpoints for running security audits, viewing reports,
and applying auto-remediation fixes.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...auth import get_current_user
from ...storage.base import User

logger = logging.getLogger(__name__)

router = APIRouter()


class AutoFixRequest(BaseModel):
    """Request to apply auto-remediation."""

    check_ids: list[str] | None = Field(
        default=None,
        description="Specific check IDs to fix. None = fix all auto-fixable.",
    )


def _get_auditor(request: Request):
    """Get the security auditor from app state."""
    auditor = getattr(request.app.state, "security_auditor", None)
    if auditor is None:
        raise HTTPException(
            status_code=503,
            detail="Security audit system not initialized",
        )
    return auditor


@router.post("/audit")
async def run_audit(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Run a full security audit."""
    auditor = _get_auditor(request)
    return await auditor.run_audit()


@router.get("/report")
async def get_latest_report(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get the most recent audit report."""
    auditor = _get_auditor(request)
    report = auditor.get_last_report()
    if report is None:
        raise HTTPException(status_code=404, detail="No audit report available. Run POST /audit first.")
    return report


@router.post("/fix")
async def auto_fix(
    body: AutoFixRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Apply auto-remediation for fixable issues."""
    auditor = _get_auditor(request)
    return await auditor.auto_fix(check_ids=body.check_ids)
