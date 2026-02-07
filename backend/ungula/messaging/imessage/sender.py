"""
iMessage sender using AppleScript or imsg CLI.

Sends messages through the macOS Messages.app.
"""

import asyncio
import logging
import shlex

logger = logging.getLogger(__name__)


async def send_via_applescript(target: str, content: str) -> bool:
    """
    Send an iMessage via AppleScript.

    Args:
        target: Phone number or email address.
        content: Message text.

    Returns:
        True if sent successfully.
    """
    # Escape for AppleScript string
    escaped_content = content.replace("\\", "\\\\").replace('"', '\\"')
    escaped_target = target.replace("\\", "\\\\").replace('"', '\\"')

    script = f'''
    tell application "Messages"
        set targetService to 1st account whose service type = iMessage
        set targetBuddy to participant "{escaped_target}" of targetService
        send "{escaped_content}" to targetBuddy
    end tell
    '''

    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)

        if proc.returncode != 0:
            logger.error("AppleScript send failed: %s", stderr.decode())
            return False
        return True
    except asyncio.TimeoutError:
        logger.error("AppleScript send timed out")
        return False
    except Exception as e:
        logger.error("AppleScript send error: %s", e)
        return False


async def send_via_cli(target: str, content: str, cli_path: str = "imsg") -> bool:
    """
    Send an iMessage via the imsg CLI tool.

    Args:
        target: Phone number or email address.
        content: Message text.
        cli_path: Path to imsg CLI.

    Returns:
        True if sent successfully.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            cli_path, "send", target, content,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)

        if proc.returncode != 0:
            logger.error("imsg send failed: %s", stderr.decode())
            return False
        return True
    except FileNotFoundError:
        logger.error("imsg CLI not found at: %s", cli_path)
        return False
    except asyncio.TimeoutError:
        logger.error("imsg send timed out")
        return False
    except Exception as e:
        logger.error("imsg send error: %s", e)
        return False
