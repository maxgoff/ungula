"""
Pairing API routes.

Endpoints for managing user pairing codes used to authenticate
channel contacts (Discord DMs, iMessage, etc.).
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...auth import get_current_user
from ...storage.base import User

logger = logging.getLogger(__name__)

router = APIRouter()


class VerifyCodeRequest(BaseModel):
    """Request to verify a pairing code."""

    code: str = Field(..., min_length=6, max_length=12)


def _get_pairing_manager(request: Request):
    """Get the pairing manager from app state."""
    manager = getattr(request.app.state, "pairing_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Pairing system not initialized")
    return manager


@router.post("/verify")
async def verify_pairing_code(
    body: VerifyCodeRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Verify a pairing code to authorize a channel contact."""
    manager = _get_pairing_manager(request)
    result = await manager.verify_code(body.code)

    if result is None:
        raise HTTPException(status_code=404, detail="Invalid or expired pairing code")

    return {
        "status": "paired",
        "channel": result.channel,
        "contact_id": result.contact_id,
        "contact_name": result.contact_name,
    }


@router.get("/pending")
async def list_pending(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List all pending pairing requests."""
    manager = _get_pairing_manager(request)
    pending = await manager.list_pending()

    return {
        "pending": [
            {
                "code": p.code,
                "channel": p.channel,
                "contact_id": p.contact_id,
                "contact_name": p.contact_name,
                "created_at": p.created_at.isoformat(),
                "expires_at": p.expires_at.isoformat(),
            }
            for p in pending
        ],
        "count": len(pending),
    }


@router.delete("/{code}")
async def revoke_code(
    code: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Revoke a pending pairing code."""
    manager = _get_pairing_manager(request)
    revoked = await manager.revoke_code(code)

    if not revoked:
        raise HTTPException(status_code=404, detail="Pairing code not found")

    return {"status": "revoked"}
