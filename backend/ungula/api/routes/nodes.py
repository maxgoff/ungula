"""
REST API routes for node management.

Provides endpoints for listing nodes, managing pairing requests,
invoking commands, and removing nodes.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


class PairInitiateRequest(BaseModel):
    name: str
    platform: str = "unknown"
    capabilities: list[str] = []


class InvokeRequest(BaseModel):
    command: str
    args: dict[str, Any] | None = None


class ExecResolveRequest(BaseModel):
    approved: bool


# --- List ---

@router.get("/")
async def list_nodes(request: Request):
    """List all nodes with current status."""
    node_manager = request.app.state.node_manager
    nodes = await node_manager.list_nodes()
    return {"nodes": nodes}


# --- Pairing initiation (WI 1) ---

@router.post("/")
async def initiate_pairing(body: PairInitiateRequest, request: Request):
    """Initiate a new pairing request. Returns node_id and token."""
    node_manager = request.app.state.node_manager
    result = await node_manager.initiate_pairing(
        name=body.name,
        platform=body.platform,
        capabilities=body.capabilities,
    )
    return result


# --- Literal routes BEFORE parameterized routes (route ordering fix) ---

@router.get("/pending")
async def list_pending(request: Request):
    """List pending pairing requests."""
    node_manager = request.app.state.node_manager
    pending = node_manager.pairing.get_pending()
    return {
        "pending": [
            {
                "node_id": r.node_id,
                "name": r.name,
                "platform": r.platform,
                "capabilities": r.capabilities,
                "created_at": r.created_at,
            }
            for r in pending
        ]
    }


# --- Exec approval endpoints (WI 9) ---

@router.get("/exec-approvals/pending")
async def list_pending_approvals(request: Request):
    """List pending exec approval requests."""
    node_manager = request.app.state.node_manager
    if not node_manager.exec_approval:
        return {"pending": []}
    pending = node_manager.exec_approval.list_pending()
    return {"pending": pending}


@router.post("/exec-approvals/{approval_id}/resolve")
async def resolve_exec_approval(approval_id: str, body: ExecResolveRequest, request: Request):
    """Approve or deny a pending exec request."""
    node_manager = request.app.state.node_manager
    if not node_manager.exec_approval:
        raise HTTPException(status_code=404, detail="Exec approval system not enabled")
    resolved = node_manager.exec_approval.resolve(approval_id, body.approved)
    if not resolved:
        raise HTTPException(status_code=404, detail="No pending approval with that ID")
    return {"status": "approved" if body.approved else "denied", "approval_id": approval_id}


# --- Parameterized routes ---

@router.get("/{node_id}")
async def get_node(node_id: str, request: Request):
    """Get details for a specific node."""
    node_manager = request.app.state.node_manager
    node = await node_manager.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.delete("/{node_id}")
async def remove_node(node_id: str, request: Request):
    """Remove a node entirely."""
    node_manager = request.app.state.node_manager
    removed = await node_manager.remove_node(node_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Node not found")
    return {"status": "removed", "node_id": node_id}


@router.post("/{node_id}/approve")
async def approve_pairing(node_id: str, request: Request):
    """Approve a pending pairing request."""
    node_manager = request.app.state.node_manager
    result = await node_manager.approve_pairing(node_id)
    if not result:
        raise HTTPException(status_code=404, detail="No pending request for this node")
    return result


@router.post("/{node_id}/reject")
async def reject_pairing(node_id: str, request: Request):
    """Reject a pending pairing request."""
    node_manager = request.app.state.node_manager
    removed = await node_manager.reject_pairing(node_id)
    if not removed:
        raise HTTPException(status_code=404, detail="No pending request for this node")
    return {"status": "rejected", "node_id": node_id}


# --- Command Invocation ---

@router.post("/{node_id}/invoke")
async def invoke_command(node_id: str, body: InvokeRequest, request: Request):
    """Manually invoke a command on a node (admin use)."""
    node_manager = request.app.state.node_manager
    result = await node_manager.invoke_command(
        command=body.command,
        args=body.args or {},
        node_id=node_id,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Command failed"))
    return result


# --- Command Logs (WI 8) ---

@router.get("/{node_id}/logs")
async def get_command_logs(node_id: str, request: Request, limit: int = 50):
    """Get command audit logs for a node."""
    node_manager = request.app.state.node_manager
    logs = await node_manager.get_command_logs(node_id, limit=limit)
    return {"logs": logs}
