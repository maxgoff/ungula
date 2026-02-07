"""
Probe for iMessage availability.

Checks if running on macOS with Messages.app and required tools.
"""

import shutil
import sys
from pathlib import Path


def is_macos() -> bool:
    """Check if running on macOS."""
    return sys.platform == "darwin"


def messages_db_path() -> Path | None:
    """Get the default iMessage database path."""
    default = Path.home() / "Library" / "Messages" / "chat.db"
    if default.exists():
        return default
    return None


def has_imsg_cli(cli_path: str = "imsg") -> bool:
    """Check if the imsg CLI tool is available."""
    return shutil.which(cli_path) is not None


def probe_imessage(cli_path: str = "imsg") -> dict:
    """
    Probe iMessage availability.

    Returns a dict with:
        available: True if iMessage can be used
        reason: Explanation if not available
        db_path: Path to chat.db if found
        has_cli: Whether imsg CLI is available
    """
    if not is_macos():
        return {
            "available": False,
            "reason": "Not running on macOS",
            "db_path": None,
            "has_cli": False,
        }

    db_path = messages_db_path()
    has_cli = has_imsg_cli(cli_path)

    if not db_path:
        return {
            "available": False,
            "reason": "Messages database not found at ~/Library/Messages/chat.db",
            "db_path": None,
            "has_cli": has_cli,
        }

    return {
        "available": True,
        "reason": "iMessage is available",
        "db_path": str(db_path),
        "has_cli": has_cli,
    }
