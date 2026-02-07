"""
Node invoke tool — dispatches commands to companion device nodes.
"""

import json
import logging
from typing import Any

from ungula.tools.base import Tool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class NodeInvokeTool(Tool):
    """Execute a command on a connected companion device (node)."""

    name = "node_invoke"
    description = "Execute a command on a connected companion device (node). Commands depend on the node's capabilities: camera.capture, screen.capture, location.get, notify.send, system.run, sms.send, etc."
    parameters = [
        ToolParameter(
            name="node_id",
            description="Target node ID, or 'any' for first capable node",
            required=False,
            default="any",
        ),
        ToolParameter(
            name="command",
            description="Command to execute: camera.capture, screen.capture, location.get, notify.send, system.run, sms.send",
            required=True,
        ),
        ToolParameter(
            name="args",
            description="Command arguments as JSON string",
            type="string",
            required=False,
        ),
    ]

    def __init__(self, node_manager: Any):
        self.node_manager = node_manager

    async def execute(self, **kwargs: Any) -> ToolResult:
        node_id = kwargs.get("node_id", "any")
        command = kwargs.get("command", "")
        args_str = kwargs.get("args", "")

        if not command:
            return ToolResult(success=False, output="", error="command is required")

        # Parse args
        args = {}
        if args_str:
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except json.JSONDecodeError:
                return ToolResult(success=False, output="", error="Invalid JSON in args")

        result = await self.node_manager.invoke_command(
            command=command,
            args=args,
            node_id=node_id if node_id != "any" else None,
        )

        if result.get("success"):
            return ToolResult(
                success=True,
                output=result.get("output", "Command executed"),
                data=result.get("data", {}),
            )
        else:
            return ToolResult(
                success=False,
                output="",
                error=result.get("error", "Command failed"),
            )
