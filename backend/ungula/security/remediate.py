"""
Auto-remediation for security audit findings.

Applies automatic fixes for issues that can be safely resolved
without user intervention (file permissions, config settings).
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def remediate_config_file_permissions(config_path: Path) -> bool:
    """Set config file to 0600 (owner-only read/write)."""
    try:
        if config_path.exists():
            config_path.chmod(0o600)
            logger.info("Set %s permissions to 0600", config_path)
            return True
    except OSError as e:
        logger.error("Failed to fix config file permissions: %s", e)
    return False


def remediate_home_dir_permissions(home_dir: Path) -> bool:
    """Set home directory to 0700 (owner-only)."""
    try:
        if home_dir.exists():
            home_dir.chmod(0o700)
            logger.info("Set %s permissions to 0700", home_dir)
            return True
    except OSError as e:
        logger.error("Failed to fix home dir permissions: %s", e)
    return False


def remediate_debug_mode(config: Any, config_path: Path) -> bool:
    """Disable reload mode in config."""
    try:
        config.server.reload = False
        # Save would need to go through save_config, but we
        # just update the in-memory config for now
        logger.info("Disabled reload mode in running config")
        return True
    except Exception as e:
        logger.error("Failed to disable debug mode: %s", e)
    return False


# Map of check IDs to their remediation functions
REMEDIATION_MAP = {
    "config-file-perms": lambda ctx: remediate_config_file_permissions(ctx["config_path"]),
    "home-dir-perms": lambda ctx: remediate_home_dir_permissions(ctx["home_dir"]),
    "debug-mode": lambda ctx: remediate_debug_mode(ctx["config"], ctx["config_path"]),
}


def apply_remediation(check_id: str, context: dict) -> bool:
    """
    Apply auto-remediation for a specific check.

    Args:
        check_id: The check ID to remediate.
        context: Dict with 'config', 'config_path', 'home_dir'.

    Returns:
        True if remediation was applied successfully.
    """
    handler = REMEDIATION_MAP.get(check_id)
    if handler is None:
        logger.warning("No auto-remediation available for check: %s", check_id)
        return False
    return handler(context)
