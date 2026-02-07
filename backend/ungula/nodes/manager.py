"""
Node manager.

Orchestrates pairing flow, token management, command dispatch,
and coordinates between the registry, pairing store, and database.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any

import bcrypt
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..storage.models import NodeModel, NodeCommandLogModel
from .pairing import NodePairingStore
from .policy import NodeCommandPolicy
from .protocol import (
    NodeEvent,
    NodeMessage,
    invoke_message,
    pair_approved_message,
    pair_rejected_message,
)
from .registry import ConnectedNode, NodeRegistry

logger = logging.getLogger(__name__)


class NodeManager:
    """Manages the full node lifecycle: pairing, connection, command dispatch."""

    def __init__(
        self,
        registry: NodeRegistry,
        pairing_store: NodePairingStore,
        policy: NodeCommandPolicy,
        storage: Any,  # SQLiteStorage
        command_timeout: int = 60,
        exec_approval: Any | None = None,
    ):
        self.registry = registry
        self.pairing = pairing_store
        self.policy = policy
        self.storage = storage
        self.command_timeout = command_timeout
        self.exec_approval = exec_approval
        self._pending_results: dict[str, asyncio.Future] = {}
        self._heartbeat_task: asyncio.Task | None = None

    # --- Pairing ---

    async def initiate_pairing(self, name: str, platform: str, capabilities: list[str]) -> dict[str, Any]:
        """Create a new pairing request. Returns node_id and token."""
        node_id = str(uuid.uuid4())

        # Create DB record in pending state
        async with self.storage.session() as session:
            node = NodeModel(
                id=node_id,
                name=name,
                platform=platform,
                capabilities=capabilities,
                status="pending",
            )
            session.add(node)
            await session.commit()

        # Create pairing request with token
        request = self.pairing.create_request(node_id, name, platform, capabilities)

        return {
            "node_id": node_id,
            "token": request.token,
            "name": name,
            "platform": platform,
        }

    async def node_initiated_pairing(
        self,
        name: str,
        platform: str,
        capabilities: list[str],
        metadata: dict[str, Any] | None = None,
        websocket: Any | None = None,
    ) -> dict[str, Any]:
        """Handle a node-initiated pairing request (node connects first, waits for approval)."""
        node_id = str(uuid.uuid4())

        # Create DB record in pending state
        async with self.storage.session() as session:
            node = NodeModel(
                id=node_id,
                name=name,
                platform=platform,
                capabilities=capabilities,
                status="pending",
                metadata_json=metadata or {},
            )
            session.add(node)
            await session.commit()

        # Create pairing request with websocket reference
        request = self.pairing.create_node_initiated_request(
            node_id, name, platform, capabilities, websocket=websocket
        )

        return {
            "node_id": node_id,
            "token": request.token,
            "name": name,
            "platform": platform,
        }

    async def approve_pairing(self, node_id: str) -> dict[str, Any] | None:
        """Approve a pending pairing request."""
        request = self.pairing.approve(node_id)
        if not request:
            return None

        # Hash the token and store it
        token_hash = bcrypt.hashpw(request.token.encode(), bcrypt.gensalt()).decode()

        async with self.storage.session() as session:
            await session.execute(
                update(NodeModel)
                .where(NodeModel.id == node_id)
                .values(status="paired", token_hash=token_hash)
            )
            await session.commit()

        result = {
            "node_id": node_id,
            "name": request.name,
            "token": request.token,  # Return token one last time for the node to store
        }

        # Notify waiting websocket if this was a node-initiated pairing
        if request.websocket:
            try:
                await request.websocket.send_json(
                    pair_approved_message(node_id, request.token).to_dict()
                )
            except Exception as e:
                logger.warning("Failed to notify node of approval: %s", e)

        return result

    async def reject_pairing(self, node_id: str) -> bool:
        """Reject a pending pairing request."""
        request = self.pairing.get_request(node_id)
        ws = request.websocket if request else None

        removed = self.pairing.reject(node_id)
        if removed:
            async with self.storage.session() as session:
                await session.execute(delete(NodeModel).where(NodeModel.id == node_id))
                await session.commit()

            # Notify waiting websocket
            if ws:
                try:
                    await ws.send_json(
                        pair_rejected_message(node_id).to_dict()
                    )
                except Exception:
                    pass

        return removed

    # --- Authentication ---

    async def authenticate_node(self, token: str) -> NodeModel | None:
        """Authenticate a node by its pairing token."""
        async with self.storage.session() as session:
            result = await session.execute(
                select(NodeModel).where(NodeModel.status.in_(["paired", "offline"]))
            )
            nodes = result.scalars().all()

            for node in nodes:
                if node.token_hash and bcrypt.checkpw(token.encode(), node.token_hash.encode()):
                    # Update status to online
                    await session.execute(
                        update(NodeModel)
                        .where(NodeModel.id == node.id)
                        .values(status="online", last_seen=datetime.utcnow())
                    )
                    await session.commit()
                    return node
        return None

    # --- Connection lifecycle ---

    async def on_node_disconnect(self, node_id: str) -> None:
        """Handle node disconnection."""
        self.registry.unregister(node_id)
        async with self.storage.session() as session:
            await session.execute(
                update(NodeModel)
                .where(NodeModel.id == node_id)
                .values(status="offline", last_seen=datetime.utcnow())
            )
            await session.commit()

    # --- Heartbeat monitor (WI 5) ---

    def start_heartbeat_monitor(self, interval: int = 30, timeout: int = 90) -> None:
        """Start a background task that sweeps for stale nodes."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            return  # Already running

        async def _sweep_loop():
            while True:
                await asyncio.sleep(interval)
                try:
                    await self._heartbeat_sweep(timeout)
                except Exception as e:
                    logger.error("Heartbeat sweep error: %s", e)

        self._heartbeat_task = asyncio.create_task(_sweep_loop())
        logger.info("Started heartbeat monitor (interval=%ds, timeout=%ds)", interval, timeout)

    async def stop_heartbeat_monitor(self) -> None:
        """Stop the heartbeat monitor task."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        self._heartbeat_task = None
        logger.info("Stopped heartbeat monitor")

    async def _heartbeat_sweep(self, timeout: int) -> None:
        """Find and disconnect stale nodes."""
        stale = self.registry.get_stale_nodes(timeout)
        for node in stale:
            logger.warning(
                "Node %s (%s) heartbeat timeout — disconnecting",
                node.name, node.node_id,
            )
            try:
                await node.websocket.close(code=4002, reason="Heartbeat timeout")
            except Exception:
                pass
            await self.on_node_disconnect(node.node_id)

    # --- Command dispatch ---

    async def invoke_command(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        node_id: str | None = None,
        invoked_by: str = "api",
    ) -> dict[str, Any]:
        """Dispatch a command to a node and wait for the result."""
        args = args or {}

        # Find target node
        if node_id and node_id != "any":
            node = self.registry.get(node_id)
            if not node:
                return {"success": False, "error": f"Node {node_id} not online"}
        else:
            # Find required capability
            required_cap = self.policy.get_required_capability(command)
            if not required_cap:
                return {"success": False, "error": f"Unknown command: {command}"}
            node = self.registry.find_capable(required_cap)
            if not node:
                return {"success": False, "error": f"No online node with capability: {required_cap}"}

        # Check policy — use platform-based check
        if not self.policy.can_execute(
            command,
            platform=node.platform,
            declared_commands=node.declared_commands,
            node_capabilities=node.capabilities,
        ):
            return {"success": False, "error": f"Node {node.name} not allowed to execute {command}"}

        # Exec approval gate for system.run
        if self.exec_approval and command == "system.run":
            run_cmd = args.get("command", "")
            if not self.exec_approval.is_allowed(run_cmd):
                approval_result = await self.exec_approval.request_approval(run_cmd, node.node_id)
                if not approval_result:
                    return {"success": False, "error": f"Exec approval denied for: {run_cmd}"}

        # Create request
        request_id = str(uuid.uuid4())[:8]
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_results[request_id] = future

        # Create audit log entry
        log_id = await self._create_command_log(
            node_id=node.node_id,
            command=command,
            args=args,
            request_id=request_id,
            invoked_by=invoked_by,
        )

        # Send invoke message
        msg = invoke_message(command, args, request_id)
        try:
            await node.websocket.send_json(msg.to_dict())
        except Exception as e:
            self._pending_results.pop(request_id, None)
            await self._update_command_log(log_id, success=False, error=str(e))
            return {"success": False, "error": f"Failed to send to node: {e}"}

        # Wait for result
        try:
            result = await asyncio.wait_for(future, timeout=self.command_timeout)
            # Update audit log with result
            await self._update_command_log(
                log_id,
                success=result.get("success", False),
                output=result.get("output", ""),
                error=result.get("error"),
                result_data=result.get("data"),
            )
            return result
        except asyncio.TimeoutError:
            self._pending_results.pop(request_id, None)
            await self._update_command_log(log_id, success=False, error=f"Timed out after {self.command_timeout}s")
            return {"success": False, "error": f"Command timed out after {self.command_timeout}s"}

    def handle_result(self, request_id: str, data: dict[str, Any]) -> None:
        """Handle a result message from a node."""
        future = self._pending_results.pop(request_id, None)
        if future and not future.done():
            future.set_result(data)

    # --- Command audit trail (WI 8) ---

    async def _create_command_log(
        self,
        node_id: str,
        command: str,
        args: dict[str, Any],
        request_id: str,
        invoked_by: str,
    ) -> str:
        """Create a command log entry before dispatch."""
        log_id = str(uuid.uuid4())
        try:
            async with self.storage.session() as session:
                log = NodeCommandLogModel(
                    id=log_id,
                    node_id=node_id,
                    command=command,
                    args_json=args,
                    request_id=request_id,
                    invoked_by=invoked_by,
                )
                session.add(log)
                await session.commit()
        except Exception as e:
            logger.warning("Failed to create command log: %s", e)
        return log_id

    async def _update_command_log(
        self,
        log_id: str,
        success: bool,
        output: str = "",
        error: str | None = None,
        result_data: dict[str, Any] | None = None,
    ) -> None:
        """Update a command log entry with result."""
        try:
            async with self.storage.session() as session:
                await session.execute(
                    update(NodeCommandLogModel)
                    .where(NodeCommandLogModel.id == log_id)
                    .values(
                        success=success,
                        output=output,
                        error=error,
                        result_data=result_data or {},
                        completed_at=datetime.utcnow(),
                    )
                )
                await session.commit()
        except Exception as e:
            logger.warning("Failed to update command log: %s", e)

    async def get_command_logs(self, node_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get command logs for a node."""
        async with self.storage.session() as session:
            result = await session.execute(
                select(NodeCommandLogModel)
                .where(NodeCommandLogModel.node_id == node_id)
                .order_by(NodeCommandLogModel.created_at.desc())
                .limit(limit)
            )
            logs = result.scalars().all()
            return [
                {
                    "id": log.id,
                    "node_id": log.node_id,
                    "command": log.command,
                    "args": log.args_json,
                    "request_id": log.request_id,
                    "success": log.success,
                    "output": log.output,
                    "error": log.error,
                    "result_data": log.result_data,
                    "invoked_by": log.invoked_by,
                    "created_at": log.created_at.isoformat() if log.created_at else None,
                    "completed_at": log.completed_at.isoformat() if log.completed_at else None,
                }
                for log in logs
            ]

    # --- Queries ---

    async def list_nodes(self) -> list[dict[str, Any]]:
        """List all nodes with their current status."""
        async with self.storage.session() as session:
            result = await session.execute(select(NodeModel))
            nodes = result.scalars().all()

        node_list = []
        for node in nodes:
            online_node = self.registry.get(node.id)
            entry = {
                "id": node.id,
                "name": node.name,
                "platform": node.platform,
                "capabilities": node.capabilities,
                "status": "online" if online_node else node.status,
                "last_seen": node.last_seen.isoformat() if node.last_seen else None,
                "created_at": node.created_at.isoformat() if node.created_at else None,
            }
            # Merge online node metadata if available
            if online_node:
                entry["declared_commands"] = online_node.declared_commands
                entry["device_family"] = online_node.device_family
                entry["version"] = online_node.version
                entry["os_version"] = online_node.os_version
                if online_node.metadata:
                    entry["metadata"] = online_node.metadata
            node_list.append(entry)
        return node_list

    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Get details for a specific node."""
        async with self.storage.session() as session:
            result = await session.execute(select(NodeModel).where(NodeModel.id == node_id))
            node = result.scalar_one_or_none()
            if not node:
                return None

            online_node = self.registry.get(node_id)
            entry = {
                "id": node.id,
                "name": node.name,
                "platform": node.platform,
                "capabilities": node.capabilities,
                "status": "online" if online_node else node.status,
                "last_seen": node.last_seen.isoformat() if node.last_seen else None,
                "created_at": node.created_at.isoformat() if node.created_at else None,
                "metadata": node.metadata_json,
            }
            if online_node:
                entry["declared_commands"] = online_node.declared_commands
                entry["device_family"] = online_node.device_family
                entry["version"] = online_node.version
                entry["os_version"] = online_node.os_version
                if online_node.metadata:
                    entry["metadata"] = {**entry.get("metadata", {}), **online_node.metadata}
            return entry

    async def remove_node(self, node_id: str) -> bool:
        """Remove a node entirely."""
        # Disconnect if online
        self.registry.unregister(node_id)
        async with self.storage.session() as session:
            result = await session.execute(delete(NodeModel).where(NodeModel.id == node_id))
            await session.commit()
            return result.rowcount > 0
