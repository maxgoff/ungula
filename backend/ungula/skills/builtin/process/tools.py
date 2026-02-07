"""
Process execution and management tools.
"""

import asyncio
import json
import logging
import shlex
from typing import Any

from ungula.config import ProcessToolConfig
from ungula.tools.base import Tool, ToolParameter, ToolResult

from .manager import ProcessManager

logger = logging.getLogger(__name__)


class ProcessExecTool(Tool):
    """Execute a command, optionally in the background."""

    name = "process_exec"
    description = "Execute a command. Use background=true to run in background and get a process_id for later management."
    parameters = [
        ToolParameter(name="command", description="Command to execute", required=True),
        ToolParameter(name="background", description="Run in background (default false)", type="boolean", required=False, default=False),
        ToolParameter(name="timeout", description="Timeout in seconds (default 30, ignored for background)", type="integer", required=False, default=30),
        ToolParameter(name="cwd", description="Working directory", required=False),
    ]

    def __init__(self, process_manager: ProcessManager, config: ProcessToolConfig):
        self.manager = process_manager
        self.config = config

    async def execute(self, **kwargs: Any) -> ToolResult:
        command = kwargs.get("command", "").strip()
        background = kwargs.get("background", False)
        timeout = min(int(kwargs.get("timeout", 30)), 120)
        cwd = kwargs.get("cwd")

        if not command:
            return ToolResult(success=False, output="", error="command is required")

        if background:
            try:
                bg = await self.manager.start(command, cwd=cwd)
                return ToolResult(
                    success=True,
                    output=f"Background process started: {bg.id}",
                    data={"process_id": bg.id, "command": command},
                )
            except RuntimeError as e:
                return ToolResult(success=False, output="", error=str(e))
        else:
            # Foreground execution
            try:
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                )
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )

                stdout_text = stdout.decode("utf-8", errors="replace").strip()
                stderr_text = stderr.decode("utf-8", errors="replace").strip()

                # Truncate
                max_out = self.config.max_output_size
                if len(stdout_text) > max_out:
                    stdout_text = stdout_text[:max_out] + "\n... (truncated)"

                if process.returncode == 0:
                    output = stdout_text
                    if stderr_text:
                        output += f"\n[stderr]: {stderr_text[:2000]}"
                    return ToolResult(
                        success=True,
                        output=output or "(no output)",
                        data={"return_code": process.returncode},
                    )
                else:
                    return ToolResult(
                        success=False,
                        output=stdout_text,
                        error=f"Exit {process.returncode}: {stderr_text[:1000] or stdout_text[:1000]}",
                        data={"return_code": process.returncode},
                    )
            except asyncio.TimeoutError:
                return ToolResult(success=False, output="", error=f"Timed out after {timeout}s")
            except Exception as e:
                return ToolResult(success=False, output="", error=str(e))


class ProcessManageTool(Tool):
    """Manage background processes."""

    name = "process_manage"
    description = "Manage background processes: list all, poll status, read logs, write stdin, or kill."
    parameters = [
        ToolParameter(name="action", description="Action: list, poll, log, write, kill", required=True),
        ToolParameter(name="process_id", description="Process ID (required for poll/log/write/kill)", required=False),
        ToolParameter(name="input", description="Input to write (for action=write)", required=False),
    ]

    def __init__(self, process_manager: ProcessManager, config: ProcessToolConfig):
        self.manager = process_manager
        self.config = config

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "")
        process_id = kwargs.get("process_id", "")
        input_data = kwargs.get("input", "")

        if action == "list":
            processes = self.manager.list_all()
            if not processes:
                return ToolResult(success=True, output="No background processes", data={"processes": []})
            lines = []
            for p in processes:
                lines.append(f"[{p['id']}] {p['status']:10s} {p['command']}")
            return ToolResult(
                success=True,
                output="\n".join(lines),
                data={"processes": processes},
            )

        if not process_id:
            return ToolResult(success=False, output="", error="process_id is required for this action")

        bg = self.manager.get(process_id)
        if not bg:
            return ToolResult(success=False, output="", error=f"Process not found: {process_id}")

        if action == "poll":
            return ToolResult(
                success=True,
                output=f"Status: {bg.status}, Return code: {bg.return_code or bg.process.returncode}",
                data=bg.to_dict(),
            )

        if action == "log":
            output = ""
            if bg.stdout_buffer:
                output += f"[stdout]\n{bg.stdout_buffer}\n"
            if bg.stderr_buffer:
                output += f"[stderr]\n{bg.stderr_buffer}\n"
            return ToolResult(
                success=True,
                output=output or "(no output yet)",
                data={"process_id": process_id},
            )

        if action == "write":
            if not input_data:
                return ToolResult(success=False, output="", error="input is required for write action")
            ok = await self.manager.write_stdin(process_id, input_data)
            if ok:
                return ToolResult(success=True, output=f"Wrote to process {process_id}")
            return ToolResult(success=False, output="", error="Failed to write (process may not accept stdin)")

        if action == "kill":
            ok = await self.manager.kill(process_id)
            if ok:
                return ToolResult(success=True, output=f"Killed process {process_id}")
            return ToolResult(success=False, output="", error="Process not running or not found")

        return ToolResult(success=False, output="", error=f"Unknown action: {action}")
