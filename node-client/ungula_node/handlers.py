"""
Built-in capability handlers for common node commands.

These are registered automatically when imported.
"""

import asyncio
import logging
import platform
import subprocess
from typing import Any

from .capabilities import capability

logger = logging.getLogger(__name__)


@capability("system.run")
async def system_run(args: dict[str, Any]) -> dict[str, Any]:
    """Execute a shell command on the node."""
    command = args.get("command", "")
    timeout = int(args.get("timeout", 30))

    if not command:
        return {"success": False, "output": "", "error": "No command provided"}

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()

        output = stdout_text
        if stderr_text:
            output += f"\n[stderr]: {stderr_text}"

        return {
            "success": process.returncode == 0,
            "output": output or "(no output)",
            "data": {"return_code": process.returncode},
        }
    except asyncio.TimeoutError:
        return {"success": False, "output": "", "error": f"Timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}


@capability("system.which")
async def system_which(args: dict[str, Any]) -> dict[str, Any]:
    """Check if a binary exists on the node and return its path."""
    binary = args.get("binary", "")
    if not binary:
        return {"success": False, "output": "", "error": "No binary specified"}

    import shutil

    path = shutil.which(binary)
    if path:
        return {"success": True, "output": path, "data": {"path": path, "binary": binary}}
    else:
        return {"success": False, "output": "", "error": f"Binary not found: {binary}"}


@capability("notify.send")
async def notify_send(args: dict[str, Any]) -> dict[str, Any]:
    """Send an OS notification."""
    title = args.get("title", "Ungula")
    message = args.get("message", "")

    if not message:
        return {"success": False, "output": "", "error": "message is required"}

    system = platform.system()
    try:
        if system == "Darwin":
            # macOS: use osascript
            script = f'display notification "{message}" with title "{title}"'
            subprocess.run(["osascript", "-e", script], check=True, timeout=5)
        elif system == "Linux":
            subprocess.run(["notify-send", title, message], check=True, timeout=5)
        else:
            return {"success": False, "output": "", "error": f"Notifications not supported on {system}"}

        return {"success": True, "output": f"Notification sent: {message}"}
    except FileNotFoundError:
        return {"success": False, "output": "", "error": "Notification command not found"}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}
