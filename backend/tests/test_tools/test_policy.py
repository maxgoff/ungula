"""
Tests for the tool policy system.

Covers ToolPolicy creation, built-in profiles, PolicyEngine filtering,
and edge cases around wildcard/deny interactions.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from ungula.tools.base import Tool, ToolResult
from ungula.tools.policy import (
    PolicyEngine,
    PolicyProfile,
    ToolPolicy,
    _PROFILE_ALLOWED,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeTool(Tool):
    """Concrete Tool subclass for testing (Tool is abstract)."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.parameters = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, output="ok")


def _make_tools(*names: str) -> list[Tool]:
    """Create a list of FakeTool instances from names."""
    return [FakeTool(name=n) for n in names]


# ===========================================================================
# ToolPolicy creation
# ===========================================================================


class TestToolPolicyCreation:
    """Tests for ToolPolicy dataclass construction."""

    def test_default_policy_is_full_profile(self):
        policy = ToolPolicy()
        assert policy.profile == PolicyProfile.FULL
        assert policy.allowed == set()
        assert policy.denied == set()

    def test_custom_allowed_list(self):
        policy = ToolPolicy(allowed={"shell_exec", "file_read"})
        assert "shell_exec" in policy.allowed
        assert "file_read" in policy.allowed

    def test_custom_denied_list(self):
        policy = ToolPolicy(denied={"dangerous_tool"})
        assert "dangerous_tool" in policy.denied

    def test_custom_profile(self):
        policy = ToolPolicy(profile=PolicyProfile.CODING)
        assert policy.profile == PolicyProfile.CODING

    def test_allowed_and_denied_coexist(self):
        policy = ToolPolicy(
            profile=PolicyProfile.MINIMAL,
            allowed={"shell_exec", "web_search"},
            denied={"web_search"},
        )
        # web_search is in both allowed and denied; denied wins
        assert not policy.is_allowed("web_search")
        assert policy.is_allowed("shell_exec")


# ===========================================================================
# Built-in profiles
# ===========================================================================


class TestBuiltInProfiles:
    """Tests for the built-in policy profiles."""

    def test_profile_enum_values(self):
        assert PolicyProfile.MINIMAL.value == "minimal"
        assert PolicyProfile.CODING.value == "coding"
        assert PolicyProfile.MESSAGING.value == "messaging"
        assert PolicyProfile.FULL.value == "full"

    def test_minimal_profile_allows_nothing(self):
        policy = ToolPolicy(profile=PolicyProfile.MINIMAL)
        assert not policy.is_allowed("shell_exec")
        assert not policy.is_allowed("file_read")
        assert not policy.is_allowed("anything")

    def test_coding_profile_tools(self):
        policy = ToolPolicy(profile=PolicyProfile.CODING)
        expected = {"shell_exec", "file_read", "file_write", "web_search"}
        for tool_name in expected:
            assert policy.is_allowed(tool_name), f"{tool_name} should be allowed"
        assert not policy.is_allowed("send_message")

    def test_messaging_profile_tools(self):
        policy = ToolPolicy(profile=PolicyProfile.MESSAGING)
        assert policy.is_allowed("web_search")
        assert not policy.is_allowed("shell_exec")
        assert not policy.is_allowed("file_write")

    def test_full_profile_allows_everything(self):
        policy = ToolPolicy(profile=PolicyProfile.FULL)
        assert policy.is_allowed("shell_exec")
        assert policy.is_allowed("any_tool_at_all")
        assert policy.is_allowed("completely_made_up")

    def test_profile_registry_keys_match_enum(self):
        """Ensure every enum value has a corresponding profile definition."""
        for profile in PolicyProfile:
            assert profile in _PROFILE_ALLOWED, (
                f"Profile {profile} missing from _PROFILE_ALLOWED"
            )


# ===========================================================================
# ToolPolicy.is_allowed logic
# ===========================================================================


class TestToolPolicyIsAllowed:
    """Tests for ToolPolicy.is_allowed resolution logic."""

    def test_effective_allowed_includes_profile_and_custom(self):
        policy = ToolPolicy(
            profile=PolicyProfile.CODING,
            allowed={"extra_tool"},
        )
        assert policy.is_allowed("shell_exec")  # from profile
        assert policy.is_allowed("extra_tool")  # custom addition
        assert not policy.is_allowed("unknown_tool")

    def test_denied_overrides_profile(self):
        policy = ToolPolicy(
            profile=PolicyProfile.CODING,
            denied={"shell_exec"},
        )
        assert not policy.is_allowed("shell_exec")
        assert policy.is_allowed("file_read")  # still in profile

    def test_denied_overrides_wildcard(self):
        """Full profile has wildcard '*', but explicit denials still apply."""
        policy = ToolPolicy(
            profile=PolicyProfile.FULL,
            denied={"dangerous_tool"},
        )
        assert policy.is_allowed("safe_tool")
        assert not policy.is_allowed("dangerous_tool")

    def test_denied_overrides_explicit_allowed(self):
        """If a tool is in both allowed and denied, denied wins."""
        policy = ToolPolicy(
            profile=PolicyProfile.MINIMAL,
            allowed={"tool_a"},
            denied={"tool_a"},
        )
        assert not policy.is_allowed("tool_a")

    def test_minimal_with_custom_allowed(self):
        """Minimal profile has empty set; adding allowed tools works."""
        policy = ToolPolicy(
            profile=PolicyProfile.MINIMAL,
            allowed={"custom_tool"},
        )
        assert policy.is_allowed("custom_tool")
        assert not policy.is_allowed("other_tool")

    def test_empty_tool_name(self):
        policy = ToolPolicy(profile=PolicyProfile.FULL)
        # Empty string is not explicitly denied, wildcard allows all
        assert policy.is_allowed("")

    def test_wildcard_in_allowed_set(self):
        """Wildcard added via custom allowed set also activates all."""
        policy = ToolPolicy(
            profile=PolicyProfile.MINIMAL,
            allowed={"*"},
        )
        assert policy.is_allowed("anything")


# ===========================================================================
# PolicyEngine.filter_tools
# ===========================================================================


class TestPolicyEngineFilterTools:
    """Tests for PolicyEngine.filter_tools method."""

    def test_filter_with_full_policy_keeps_all(self):
        engine = PolicyEngine()  # default is FULL
        tools = _make_tools("shell_exec", "file_read", "web_search")
        filtered = engine.filter_tools(tools)
        assert len(filtered) == 3
        assert [t.name for t in filtered] == ["shell_exec", "file_read", "web_search"]

    def test_filter_with_minimal_policy_removes_all(self):
        engine = PolicyEngine(default_policy=ToolPolicy(profile=PolicyProfile.MINIMAL))
        tools = _make_tools("shell_exec", "file_read")
        filtered = engine.filter_tools(tools)
        assert len(filtered) == 0

    def test_filter_with_coding_policy(self):
        engine = PolicyEngine()
        policy = ToolPolicy(profile=PolicyProfile.CODING)
        tools = _make_tools("shell_exec", "send_message", "file_read", "web_search")
        filtered = engine.filter_tools(tools, policy=policy)
        names = [t.name for t in filtered]
        assert "shell_exec" in names
        assert "file_read" in names
        assert "web_search" in names
        assert "send_message" not in names

    def test_filter_with_denied_list(self):
        policy = ToolPolicy(
            profile=PolicyProfile.FULL,
            denied={"shell_exec"},
        )
        engine = PolicyEngine(default_policy=policy)
        tools = _make_tools("shell_exec", "file_read", "web_search")
        filtered = engine.filter_tools(tools)
        names = [t.name for t in filtered]
        assert "shell_exec" not in names
        assert "file_read" in names
        assert "web_search" in names

    def test_filter_with_custom_allowed(self):
        policy = ToolPolicy(
            profile=PolicyProfile.MINIMAL,
            allowed={"special_tool"},
        )
        engine = PolicyEngine()
        tools = _make_tools("special_tool", "other_tool")
        filtered = engine.filter_tools(tools, policy=policy)
        assert len(filtered) == 1
        assert filtered[0].name == "special_tool"

    def test_filter_empty_tool_list(self):
        engine = PolicyEngine()
        filtered = engine.filter_tools([])
        assert filtered == []

    def test_filter_preserves_tool_order(self):
        engine = PolicyEngine()
        names_in = ["z_tool", "a_tool", "m_tool"]
        tools = _make_tools(*names_in)
        filtered = engine.filter_tools(tools)
        assert [t.name for t in filtered] == names_in

    def test_override_policy_takes_precedence(self):
        """Passing a policy to filter_tools overrides the engine default."""
        default = ToolPolicy(profile=PolicyProfile.MINIMAL)
        override = ToolPolicy(profile=PolicyProfile.FULL)
        engine = PolicyEngine(default_policy=default)
        tools = _make_tools("shell_exec")
        # Default would deny everything
        assert engine.filter_tools(tools) == []
        # Override allows everything
        assert len(engine.filter_tools(tools, policy=override)) == 1


# ===========================================================================
# PolicyEngine.filter_definitions
# ===========================================================================


class TestPolicyEngineFilterDefinitions:
    """Tests for PolicyEngine.filter_definitions (dict-based filtering)."""

    def test_filter_definitions_basic(self):
        engine = PolicyEngine()
        policy = ToolPolicy(profile=PolicyProfile.CODING)
        definitions = [
            {"name": "shell_exec", "description": "Run shell commands"},
            {"name": "send_message", "description": "Send a message"},
            {"name": "file_read", "description": "Read a file"},
        ]
        filtered = engine.filter_definitions(definitions, policy=policy)
        names = [d["name"] for d in filtered]
        assert "shell_exec" in names
        assert "file_read" in names
        assert "send_message" not in names

    def test_filter_definitions_missing_name_key(self):
        """Definitions without a 'name' key get empty string, which is
        only allowed if the policy allows empty strings."""
        engine = PolicyEngine(default_policy=ToolPolicy(profile=PolicyProfile.CODING))
        definitions = [{"description": "no name here"}]
        filtered = engine.filter_definitions(definitions)
        # Empty string is not in the coding profile allowed set
        assert len(filtered) == 0

    def test_filter_definitions_empty_list(self):
        engine = PolicyEngine()
        filtered = engine.filter_definitions([])
        assert filtered == []

    def test_filter_definitions_full_profile_keeps_all(self):
        engine = PolicyEngine()
        definitions = [
            {"name": "tool_a"},
            {"name": "tool_b"},
            {"name": "tool_c"},
        ]
        filtered = engine.filter_definitions(definitions)
        assert len(filtered) == 3
