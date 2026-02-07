"""
Exec approval system for gating arbitrary command execution on nodes.

Commands go through an allowlist check first. If not allowed, an approval
request is created and waits (async) for an operator to approve or deny.
"""

import asyncio
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class ExecApprovalManager:
    """Gates system.run commands through an allowlist + approval flow."""

    def __init__(
        self,
        allowed_patterns: list[str] | None = None,
        approval_timeout: int = 300,
    ):
        self._allowed = set(allowed_patterns or [])
        self._timeout = approval_timeout
        self._pending: dict[str, dict[str, Any]] = {}  # approval_id -> request info
        self._futures: dict[str, asyncio.Future] = {}  # approval_id -> future

    def is_allowed(self, command: str) -> bool:
        """Check if a command is in the allowlist."""
        if not self._allowed:
            return False  # No allowlist = everything needs approval
        # Check exact match or prefix match
        for pattern in self._allowed:
            if command == pattern or command.startswith(pattern + " "):
                return True
        return False

    async def request_approval(self, command: str, node_id: str) -> bool:
        """Request approval for a command. Blocks until resolved or timeout."""
        approval_id = str(uuid.uuid4())[:8]
        self._pending[approval_id] = {
            "id": approval_id,
            "command": command,
            "node_id": node_id,
            "created_at": time.time(),
        }

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._futures[approval_id] = future

        logger.info(
            "Exec approval requested: %s (command=%s, node=%s)",
            approval_id, command, node_id,
        )

        try:
            result = await asyncio.wait_for(future, timeout=self._timeout)
            return result
        except asyncio.TimeoutError:
            logger.warning("Exec approval timed out: %s", approval_id)
            self._pending.pop(approval_id, None)
            self._futures.pop(approval_id, None)
            return False

    def resolve(self, approval_id: str, approved: bool) -> bool:
        """Resolve a pending approval request."""
        future = self._futures.pop(approval_id, None)
        self._pending.pop(approval_id, None)

        if future and not future.done():
            future.set_result(approved)
            logger.info("Exec approval resolved: %s -> %s", approval_id, "approved" if approved else "denied")
            return True
        return False

    def list_pending(self) -> list[dict[str, Any]]:
        """List all pending approval requests."""
        # Clean up expired
        now = time.time()
        expired = [
            aid for aid, info in self._pending.items()
            if (now - info["created_at"]) > self._timeout
        ]
        for aid in expired:
            self._pending.pop(aid, None)
            future = self._futures.pop(aid, None)
            if future and not future.done():
                future.set_result(False)

        return list(self._pending.values())
