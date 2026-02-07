"""
Tool Policy System.

Provides a way to restrict which tools are available to agents based on
named profiles or custom allow/deny lists. Policies are applied before
sending tool definitions to the LLM.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .base import Tool

logger = logging.getLogger(__name__)


class PolicyProfile(str, Enum):
    """Built-in policy profiles."""

    MINIMAL = "minimal"
    CODING = "coding"
    MESSAGING = "messaging"
    FULL = "full"


# Built-in profile definitions: sets of allowed tool name patterns / tags
_PROFILE_ALLOWED: dict[PolicyProfile, frozenset[str]] = {
    PolicyProfile.MINIMAL: frozenset(),  # No tools
    PolicyProfile.CODING: frozenset({
        "shell_exec",
        "file_read",
        "file_write",
        "file_edit",
        "file_search",
        "process_exec",
        "process_manage",
        "web_search",
        "browser",
        "workspace_write",
    }),
    PolicyProfile.MESSAGING: frozenset({
        "web_search",
        "node_invoke",
    }),
    PolicyProfile.FULL: frozenset({"*"}),  # All tools
}


@dataclass
class ToolPolicy:
    """
    Defines which tools are allowed or denied.

    Resolution order:
    1. If ``profile`` is set, start from the profile's allow set.
    2. ``allowed`` adds to the set (union).
    3. ``denied`` removes from the set (difference).
    4. A tool passes if its name is in the final allow set,
       or if the allow set contains '*' (wildcard).
    """

    profile: PolicyProfile = PolicyProfile.FULL
    allowed: set[str] = field(default_factory=set)
    denied: set[str] = field(default_factory=set)

    def _effective_allowed(self) -> set[str]:
        """Compute the effective allow set."""
        base = set(_PROFILE_ALLOWED.get(self.profile, frozenset()))
        base |= self.allowed
        base -= self.denied
        return base

    def is_allowed(self, tool_name: str) -> bool:
        """Check if a tool is allowed under this policy."""
        effective = self._effective_allowed()
        if "*" in effective:
            # Wildcard allows all, but still respect explicit denials
            return tool_name not in self.denied
        return tool_name in effective


class PolicyEngine:
    """Applies tool policies to filter tool lists."""

    def __init__(self, default_policy: ToolPolicy | None = None):
        self.default_policy = default_policy or ToolPolicy()

    def filter_tools(
        self,
        tools: list[Tool],
        policy: ToolPolicy | None = None,
    ) -> list[Tool]:
        """Filter a list of tools according to a policy.

        Args:
            tools: All available tools.
            policy: Policy to apply. Falls back to engine default.

        Returns:
            Filtered list of tools that pass the policy.
        """
        active_policy = policy or self.default_policy
        allowed = []
        for tool in tools:
            if active_policy.is_allowed(tool.name):
                allowed.append(tool)
            else:
                logger.debug("Policy denied tool: %s", tool.name)
        return allowed

    def filter_definitions(
        self,
        definitions: list[dict[str, Any]],
        policy: ToolPolicy | None = None,
    ) -> list[dict[str, Any]]:
        """Filter tool definitions (dict format) according to a policy.

        Useful for filtering get_tool_definitions() output directly.
        """
        active_policy = policy or self.default_policy
        return [
            d for d in definitions
            if active_policy.is_allowed(d.get("name", ""))
        ]
