"""
Node command policy.

Determines which commands a node is allowed to execute based on
its platform, declared commands, and config overrides.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Legacy mapping — kept for backward compatibility with capability-based auth
COMMAND_CAPABILITY_MAP: dict[str, str] = {
    "camera.capture": "camera",
    "camera.stream": "camera",
    "screen.capture": "screen",
    "screen.record": "screen",
    "location.get": "location",
    "notify.send": "notify",
    "system.run": "system.run",
    "system.which": "system.which",
    "sms.send": "sms.send",
    "clipboard.get": "clipboard",
    "clipboard.set": "clipboard",
    "audio.play": "audio",
    "audio.record": "audio",
    "canvas.draw": "canvas",
}

# Platform defaults: what commands each platform can run out-of-the-box
PLATFORM_DEFAULTS: dict[str, list[str]] = {
    "ios": [
        "canvas.draw", "camera.capture", "camera.stream",
        "screen.capture", "screen.record", "location.get",
    ],
    "android": [
        "canvas.draw", "camera.capture", "camera.stream",
        "screen.capture", "screen.record", "location.get", "sms.send",
    ],
    "macos": [
        "canvas.draw", "camera.capture", "camera.stream",
        "screen.capture", "screen.record", "location.get",
        "system.run", "system.which", "clipboard.get", "clipboard.set",
        "audio.play", "audio.record",
    ],
    "darwin": [  # alias for macos
        "canvas.draw", "camera.capture", "camera.stream",
        "screen.capture", "screen.record", "location.get",
        "system.run", "system.which", "clipboard.get", "clipboard.set",
        "audio.play", "audio.record",
    ],
    "linux": [
        "system.run", "system.which", "clipboard.get", "clipboard.set",
        "audio.play", "audio.record",
    ],
    "windows": [
        "system.run", "system.which", "clipboard.get", "clipboard.set",
    ],
}

# Unknown platforms are permissive — allow all known commands
_ALL_COMMANDS = sorted(set(COMMAND_CAPABILITY_MAP.keys()))


def normalize_platform(raw: str) -> str:
    """Normalize a platform string to lowercase, canonical form."""
    p = raw.strip().lower()
    if p in ("macos", "mac", "osx", "mac os x"):
        return "macos"
    if p in ("darwin",):
        return "darwin"
    return p


class NodeCommandPolicy:
    """Determines if a node can execute a given command."""

    def __init__(
        self,
        allow_commands: list[str] | None = None,
        deny_commands: list[str] | None = None,
        extra_mappings: dict[str, str] | None = None,
    ):
        self._allow = set(allow_commands) if allow_commands else set()
        self._deny = set(deny_commands) if deny_commands else set()
        # Legacy capability map
        self._map = dict(COMMAND_CAPABILITY_MAP)
        if extra_mappings:
            self._map.update(extra_mappings)

    def resolve_allowlist(self, platform: str, declared_commands: list[str] | None = None) -> set[str]:
        """Resolve the set of allowed commands for a platform + declared commands."""
        norm = normalize_platform(platform)
        base = set(PLATFORM_DEFAULTS.get(norm, _ALL_COMMANDS))

        # If the node explicitly declared commands, intersect with platform defaults
        if declared_commands:
            base = base & set(declared_commands)

        # Apply config overrides
        if self._allow:
            base |= self._allow
        if self._deny:
            base -= self._deny

        return base

    def can_execute(
        self,
        command: str,
        platform: str | list[str] = "unknown",
        declared_commands: list[str] | None = None,
        node_capabilities: list[str] | None = None,
    ) -> bool:
        """Check if a node is allowed to execute a command.

        Supports both platform-based policy (new) and capability-based (legacy).
        If platform is a list, treat it as legacy node_capabilities for backward compat.
        """
        # Legacy calling convention: can_execute("cmd", ["cap1", "cap2"])
        if isinstance(platform, list):
            node_capabilities = platform
            platform = "unknown"

        # Explicit deny always wins
        if command in self._deny:
            return False
        # Explicit allow always wins
        if command in self._allow:
            return True

        # Platform-based check
        if platform and platform != "unknown":
            allowed = self.resolve_allowlist(platform, declared_commands)
            return command in allowed

        # Legacy capability-based fallback
        if node_capabilities is not None:
            required = self._map.get(command)
            if required is None:
                logger.warning("Unknown node command: %s", command)
                return False
            return required in node_capabilities

        # Unknown platform, no capabilities — permissive fallback
        return command in _ALL_COMMANDS

    # --- Backward-compat shims ---

    def list_commands_for_capabilities(self, capabilities: list[str]) -> list[str]:
        """List all commands available for a set of capabilities."""
        return [cmd for cmd, cap in self._map.items() if cap in capabilities]

    def get_required_capability(self, command: str) -> str | None:
        """Get the capability required for a command."""
        return self._map.get(command)
