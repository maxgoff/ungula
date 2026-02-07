"""
Subagent API routes.

Endpoints for listing, monitoring, and cancelling subagent sessions.
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...agents.subagent import SubagentStatus
from ...auth import get_current_user
from ...storage.base import User

logger = logging.getLogger(__name__)

router = APIRouter()


class SpawnRequest(BaseModel):
    """Request to spawn a subagent."""

    task: str = Field(..., max_length=10_000)
    parent_conversation_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _get_subagent_manager(request: Request):
    """Get the subagent manager from app state."""
    manager = getattr(request.app.state, "subagent_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Subagent system not initialized")
    return manager


@router.post("/spawn")
async def spawn_subagent(
    body: SpawnRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Spawn a new subagent."""
    manager = _get_subagent_manager(request)
    agent_runner = request.app.state.agent_runner
    storage = request.app.state.storage

    try:
        session = await manager.spawn(
            task_description=body.task,
            parent_conversation_id=body.parent_conversation_id,
            agent_runner=agent_runner,
            storage=storage,
            metadata=body.metadata,
        )
        return session.to_dict()
    except RuntimeError as e:
        raise HTTPException(status_code=429, detail=str(e))


@router.get("/")
async def list_subagents(
    request: Request,
    user: User = Depends(get_current_user),
    status: str | None = None,
    parent_id: UUID | None = None,
) -> dict[str, Any]:
    """List subagent sessions."""
    manager = _get_subagent_manager(request)

    filter_status = None
    if status:
        try:
            filter_status = SubagentStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    sessions = await manager.list_sessions(
        parent_id=parent_id,
        status=filter_status,
    )

    return {
        "sessions": [s.to_dict() for s in sessions],
        "count": len(sessions),
    }


@router.get("/{session_id}")
async def get_subagent(
    session_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get a subagent session."""
    manager = _get_subagent_manager(request)
    session = await manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Subagent session not found")
    return session.to_dict()


@router.post("/{session_id}/cancel")
async def cancel_subagent(
    session_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Cancel a running subagent."""
    manager = _get_subagent_manager(request)
    cancelled = await manager.cancel(session_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Subagent session not found")
    return {"status": "cancelled"}


@router.get("/{session_id}/result")
async def get_subagent_result(
    session_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get a subagent's result (waits if still running)."""
    manager = _get_subagent_manager(request)
    session = await manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Subagent session not found")

    if session.status == SubagentStatus.RUNNING:
        # Wait for result (with timeout handled by collect_result)
        result = await manager.collect_result(session_id)
    else:
        result = session.result

    return {
        "session_id": str(session_id),
        "status": session.status.value,
        "result": result,
        "error": session.error,
    }
