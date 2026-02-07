"""
Shell Execution Tool.

Provides the ability to execute shell commands with security constraints.
Uses proper command parsing and validation instead of simple substring matching.
"""

import asyncio
import logging
import re
import shlex
from typing import Any

from ungula.config import ShellToolConfig
from ungula.tools.base import Tool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

# Commands that are never allowed regardless of config
DANGEROUS_BASE_COMMANDS = frozenset({
    "rm", "rmdir", "mkfs", "dd", "fdisk", "parted",
    "shutdown", "reboot", "halt", "poweroff", "init",
    "passwd", "useradd", "userdel", "usermod", "groupadd", "groupdel",
    "mount", "umount", "chroot",
    "iptables", "ip6tables", "nft",
    "systemctl", "service",
    "crontab",
    "nc", "ncat", "netcat",
    "curl", "wget",  # Network access -- allow via allowed_commands if needed
})

# Shell metacharacters / injection patterns
_SHELL_INJECTION_PATTERNS = re.compile(
    r"(?:"
    r"\$\("           # $(...)
    r"|`"             # backtick substitution
    r"|\|\|"          # logical OR
    r"|&&"            # logical AND
    r"|;"             # command separator
    r"|\bsudo\b"     # privilege escalation
    r"|\bsu\b"        # switch user
    r"|\beval\b"      # eval
    r"|\bexec\b"      # exec
    r"|\bsource\b"    # source
    r"|>\s*/dev/"     # redirect to devices
    r"|>\s*/etc/"     # redirect to system config
    r"|>\s*/proc/"    # redirect to proc
    r"|>\s*/sys/"     # redirect to sys
    r"|>\s*/boot/"    # redirect to boot
    r")"
)

# Whether the command requires shell=True (contains pipes, globs, redirects)
_NEEDS_SHELL = re.compile(r"[|><*?]")


def validate_command(command: str, config: ShellToolConfig) -> str | None:
    """Validate a shell command. Returns error message if invalid, None if ok."""
    if not command:
        return "No command provided"

    # Check for shell injection patterns
    if _SHELL_INJECTION_PATTERNS.search(command):
        return "Command contains disallowed shell metacharacters or patterns"

    # Parse the command to get the base executable
    try:
        parts = shlex.split(command)
    except ValueError as e:
        return f"Malformed command: {e}"

    if not parts:
        return "Empty command"

    base_cmd = parts[0].split("/")[-1]  # Handle full paths like /usr/bin/rm

    # Check against dangerous base commands
    if base_cmd in DANGEROUS_BASE_COMMANDS:
        return f"Command '{base_cmd}' is not allowed"

    # Config-level blocked patterns (still useful for custom patterns)
    for blocked in config.blocked_commands:
        if blocked in command:
            return f"Command blocked: matches pattern '{blocked}'"

    # Config-level allowed commands (whitelist mode)
    if config.allowed_commands:
        allowed = False
        for prefix in config.allowed_commands:
            if command.startswith(prefix):
                allowed = True
                break
        if not allowed:
            return "Command not in allowed list"

    return None


class ShellTool(Tool):
    """Execute shell commands with security constraints."""

    name = "shell_exec"
    description = "Execute a shell command and return the output. Use for system tasks, file operations, and running CLI tools."
    parameters = [
        ToolParameter(
            name="command",
            description="The shell command to execute",
            type="string",
            required=True,
        ),
        ToolParameter(
            name="timeout",
            description="Timeout in seconds (default 10, max 30)",
            type="integer",
            required=False,
            default=10,
        ),
    ]

    def __init__(self, config: ShellToolConfig):
        self.config = config

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a shell command."""
        command = kwargs.get("command", "").strip()

        # Validate command
        error = validate_command(command, self.config)
        if error:
            return ToolResult(success=False, output="", error=error)

        timeout = min(kwargs.get("timeout", 10), self.config.max_timeout)
        cwd = self.config.working_dir

        try:
            # Use shell=False for simple commands, shell=True only when pipes/globs needed
            if _NEEDS_SHELL.search(command):
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                )
            else:
                parts = shlex.split(command)
                process = await asyncio.create_subprocess_exec(
                    *parts,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )

            stdout_text = stdout.decode("utf-8", errors="replace").strip()
            stderr_text = stderr.decode("utf-8", errors="replace").strip()

            # Truncate very long output
            max_output = 8000
            if len(stdout_text) > max_output:
                stdout_text = stdout_text[:max_output] + "\n... (output truncated)"

            if process.returncode == 0:
                output = stdout_text
                if stderr_text:
                    output += f"\n[stderr]: {stderr_text[:1000]}"
                return ToolResult(
                    success=True,
                    output=output or "(no output)",
                    data={"return_code": process.returncode},
                )
            else:
                error_msg = stderr_text or stdout_text or f"Exit code {process.returncode}"
                return ToolResult(
                    success=False,
                    output=stdout_text,
                    error=f"Command failed (exit {process.returncode}): {error_msg[:500]}",
                    data={"return_code": process.returncode},
                )

        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error=f"Command timed out after {timeout} seconds",
            )
        except Exception as e:
            logger.error("Shell execution error: %s", e)
            return ToolResult(
                success=False,
                output="",
                error=f"Execution error: {str(e)}",
            )
