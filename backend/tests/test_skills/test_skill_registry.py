"""
Tests for the SkillRegistry from ungula.skills.loader.

Covers registration, unregistration, listing, eligibility filtering,
tool collection, prompt building, and enable/disable operations.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from ungula.skills.loader import LoadedSkill, SkillMetadata, SkillRegistry, SkillRequirements
from ungula.tools.base import Tool, ToolParameter, ToolResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class DummyTool(Tool):
    """Concrete Tool subclass for testing."""

    def __init__(self, name: str = "dummy", description: str = "A dummy tool"):
        self.name = name
        self.description = description
        self.parameters: list[ToolParameter] = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, output="ok")


def _make_skill(
    name: str,
    eligible: bool = True,
    enabled: bool = True,
    body: str = "skill body",
    tools: list[Tool] | None = None,
    inject_prompt: bool = True,
    description: str = "",
    source: str = "user",
) -> LoadedSkill:
    """Create a LoadedSkill for testing."""
    metadata = SkillMetadata(
        name=name,
        enabled=enabled,
        inject_prompt=inject_prompt,
        description=description,
    )
    return LoadedSkill(
        metadata=metadata,
        skill_dir=Path(f"/tmp/skills/{name}"),
        body=body,
        tools=tools or [],
        eligible=eligible,
        source=source,
    )


# ---------------------------------------------------------------------------
# Tests: register / get / unregister
# ---------------------------------------------------------------------------

class TestRegistration:
    """Tests for register, get, and unregister."""

    def test_register_and_get(self):
        registry = SkillRegistry()
        skill = _make_skill("alpha")
        registry.register(skill)
        assert registry.get("alpha") is skill

    def test_get_unknown_returns_none(self):
        registry = SkillRegistry()
        assert registry.get("nonexistent") is None

    def test_unregister_removes_skill(self):
        registry = SkillRegistry()
        skill = _make_skill("alpha")
        registry.register(skill)
        registry.unregister("alpha")
        assert registry.get("alpha") is None

    def test_unregister_nonexistent_is_noop(self):
        """Unregistering a name that was never registered should not raise."""
        registry = SkillRegistry()
        registry.unregister("ghost")  # no error

    def test_register_overwrites_existing(self):
        """Registering with the same name replaces the previous entry."""
        registry = SkillRegistry()
        skill_v1 = _make_skill("alpha", body="v1")
        skill_v2 = _make_skill("alpha", body="v2")
        registry.register(skill_v1)
        registry.register(skill_v2)
        assert registry.get("alpha").body == "v2"

    def test_register_multiple_distinct(self):
        registry = SkillRegistry()
        registry.register(_make_skill("a"))
        registry.register(_make_skill("b"))
        registry.register(_make_skill("c"))
        assert len(registry.list_skills()) == 3


# ---------------------------------------------------------------------------
# Tests: list_skills
# ---------------------------------------------------------------------------

class TestListSkills:
    """Tests for list_skills."""

    def test_empty_registry(self):
        registry = SkillRegistry()
        assert registry.list_skills() == []

    def test_returns_all_skills(self):
        registry = SkillRegistry()
        registry.register(_make_skill("a"))
        registry.register(_make_skill("b", eligible=False))
        registry.register(_make_skill("c", enabled=False))
        result = registry.list_skills()
        assert len(result) == 3

    def test_returns_list_not_dict_values(self):
        registry = SkillRegistry()
        registry.register(_make_skill("x"))
        result = registry.list_skills()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Tests: list_eligible
# ---------------------------------------------------------------------------

class TestListEligible:
    """Tests for list_eligible (only eligible AND enabled)."""

    def test_empty_registry(self):
        registry = SkillRegistry()
        assert registry.list_eligible() == []

    def test_only_eligible_and_enabled(self):
        registry = SkillRegistry()
        registry.register(_make_skill("ok", eligible=True, enabled=True))
        registry.register(_make_skill("disabled", eligible=True, enabled=False))
        registry.register(_make_skill("ineligible", eligible=False, enabled=True))
        registry.register(_make_skill("both-bad", eligible=False, enabled=False))
        result = registry.list_eligible()
        assert len(result) == 1
        assert result[0].metadata.name == "ok"

    def test_all_eligible(self):
        registry = SkillRegistry()
        registry.register(_make_skill("a"))
        registry.register(_make_skill("b"))
        assert len(registry.list_eligible()) == 2

    def test_none_eligible(self):
        registry = SkillRegistry()
        registry.register(_make_skill("a", eligible=False))
        registry.register(_make_skill("b", enabled=False))
        assert registry.list_eligible() == []


# ---------------------------------------------------------------------------
# Tests: get_all_tools
# ---------------------------------------------------------------------------

class TestGetAllTools:
    """Tests for get_all_tools (tools from eligible skills only)."""

    def test_no_skills_returns_empty(self):
        registry = SkillRegistry()
        assert registry.get_all_tools() == []

    def test_collects_tools_from_eligible_skills(self):
        t1 = DummyTool(name="tool-a")
        t2 = DummyTool(name="tool-b")
        registry = SkillRegistry()
        registry.register(_make_skill("s1", tools=[t1]))
        registry.register(_make_skill("s2", tools=[t2]))
        tools = registry.get_all_tools()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"tool-a", "tool-b"}

    def test_excludes_tools_from_ineligible_skills(self):
        t1 = DummyTool(name="tool-good")
        t2 = DummyTool(name="tool-bad")
        registry = SkillRegistry()
        registry.register(_make_skill("s1", tools=[t1], eligible=True))
        registry.register(_make_skill("s2", tools=[t2], eligible=False))
        tools = registry.get_all_tools()
        assert len(tools) == 1
        assert tools[0].name == "tool-good"

    def test_excludes_tools_from_disabled_skills(self):
        t1 = DummyTool(name="tool-enabled")
        t2 = DummyTool(name="tool-disabled")
        registry = SkillRegistry()
        registry.register(_make_skill("s1", tools=[t1], enabled=True))
        registry.register(_make_skill("s2", tools=[t2], enabled=False))
        tools = registry.get_all_tools()
        assert len(tools) == 1
        assert tools[0].name == "tool-enabled"

    def test_skill_with_no_tools(self):
        registry = SkillRegistry()
        registry.register(_make_skill("s1", tools=[]))
        assert registry.get_all_tools() == []

    def test_multiple_tools_per_skill(self):
        t1 = DummyTool(name="a")
        t2 = DummyTool(name="b")
        t3 = DummyTool(name="c")
        registry = SkillRegistry()
        registry.register(_make_skill("s1", tools=[t1, t2]))
        registry.register(_make_skill("s2", tools=[t3]))
        tools = registry.get_all_tools()
        assert len(tools) == 3


# ---------------------------------------------------------------------------
# Tests: build_skills_prompt
# ---------------------------------------------------------------------------

class TestBuildSkillsPrompt:
    """Tests for build_skills_prompt."""

    def test_no_eligible_skills_returns_empty(self):
        registry = SkillRegistry()
        assert registry.build_skills_prompt() == ""

    def test_no_eligible_with_only_ineligible(self):
        registry = SkillRegistry()
        registry.register(_make_skill("a", eligible=False, body="should not appear"))
        assert registry.build_skills_prompt() == ""

    def test_single_skill_prompt(self):
        registry = SkillRegistry()
        registry.register(_make_skill("my-skill", body="Do something useful."))
        prompt = registry.build_skills_prompt()
        assert "### my-skill" in prompt
        assert "Do something useful." in prompt

    def test_includes_description_in_header(self):
        registry = SkillRegistry()
        registry.register(
            _make_skill("my-skill", body="body", description="A helpful skill")
        )
        prompt = registry.build_skills_prompt()
        assert "### my-skill -- A helpful skill" in prompt

    def test_includes_skill_location(self):
        registry = SkillRegistry()
        registry.register(_make_skill("loc-skill", body="Body here."))
        prompt = registry.build_skills_prompt()
        assert "**Skill location:**" in prompt
        assert "/tmp/skills/loc-skill" in prompt

    def test_multiple_skills_separated_by_divider(self):
        registry = SkillRegistry()
        registry.register(_make_skill("alpha", body="Alpha body"))
        registry.register(_make_skill("beta", body="Beta body"))
        prompt = registry.build_skills_prompt()
        assert "---" in prompt
        assert "Alpha body" in prompt
        assert "Beta body" in prompt

    def test_inject_prompt_false_excluded(self):
        registry = SkillRegistry()
        registry.register(_make_skill("visible", body="I am visible", inject_prompt=True))
        registry.register(_make_skill("hidden", body="I am hidden", inject_prompt=False))
        prompt = registry.build_skills_prompt()
        assert "I am visible" in prompt
        assert "I am hidden" not in prompt
        assert "hidden" not in prompt

    def test_empty_body_excluded(self):
        """Skills with whitespace-only bodies are excluded from the prompt."""
        registry = SkillRegistry()
        registry.register(_make_skill("empty", body="   "))
        registry.register(_make_skill("nonempty", body="Real content"))
        prompt = registry.build_skills_prompt()
        assert "empty" not in prompt.split("---")[0] if "---" in prompt else True
        assert "Real content" in prompt

    def test_disabled_skill_excluded_from_prompt(self):
        registry = SkillRegistry()
        registry.register(_make_skill("on", body="On body", enabled=True))
        registry.register(_make_skill("off", body="Off body", enabled=False))
        prompt = registry.build_skills_prompt()
        assert "On body" in prompt
        assert "Off body" not in prompt

    def test_all_inject_false_returns_empty(self):
        """If all eligible skills have inject_prompt=False, prompt is empty."""
        registry = SkillRegistry()
        registry.register(_make_skill("a", body="body a", inject_prompt=False))
        registry.register(_make_skill("b", body="body b", inject_prompt=False))
        assert registry.build_skills_prompt() == ""


# ---------------------------------------------------------------------------
# Tests: enable_skill / disable_skill
# ---------------------------------------------------------------------------

class TestEnableDisable:
    """Tests for enable_skill and disable_skill."""

    def test_enable_found_skill(self):
        registry = SkillRegistry()
        registry.register(_make_skill("alpha", enabled=False))
        result = registry.enable_skill("alpha")
        assert result is True
        assert registry.get("alpha").metadata.enabled is True

    def test_enable_not_found(self):
        registry = SkillRegistry()
        result = registry.enable_skill("ghost")
        assert result is False

    def test_disable_found_skill(self):
        registry = SkillRegistry()
        registry.register(_make_skill("alpha", enabled=True))
        result = registry.disable_skill("alpha")
        assert result is True
        assert registry.get("alpha").metadata.enabled is False

    def test_disable_not_found(self):
        registry = SkillRegistry()
        result = registry.disable_skill("ghost")
        assert result is False

    def test_enable_already_enabled_is_idempotent(self):
        registry = SkillRegistry()
        registry.register(_make_skill("alpha", enabled=True))
        assert registry.enable_skill("alpha") is True
        assert registry.get("alpha").metadata.enabled is True

    def test_disable_already_disabled_is_idempotent(self):
        registry = SkillRegistry()
        registry.register(_make_skill("alpha", enabled=False))
        assert registry.disable_skill("alpha") is True
        assert registry.get("alpha").metadata.enabled is False

    def test_disable_then_enable_roundtrip(self):
        registry = SkillRegistry()
        registry.register(_make_skill("alpha", enabled=True))
        registry.disable_skill("alpha")
        assert registry.get("alpha").metadata.enabled is False
        registry.enable_skill("alpha")
        assert registry.get("alpha").metadata.enabled is True

    def test_disable_removes_from_eligible(self):
        registry = SkillRegistry()
        registry.register(_make_skill("alpha", eligible=True, enabled=True))
        assert len(registry.list_eligible()) == 1
        registry.disable_skill("alpha")
        assert len(registry.list_eligible()) == 0

    def test_enable_adds_to_eligible_when_also_eligible(self):
        registry = SkillRegistry()
        registry.register(_make_skill("alpha", eligible=True, enabled=False))
        assert len(registry.list_eligible()) == 0
        registry.enable_skill("alpha")
        assert len(registry.list_eligible()) == 1

    def test_enable_does_not_make_ineligible_skill_eligible(self):
        """Enabling a skill does not change its eligibility flag."""
        registry = SkillRegistry()
        registry.register(_make_skill("alpha", eligible=False, enabled=False))
        registry.enable_skill("alpha")
        # Enabled is now True, but eligible is still False
        assert registry.get("alpha").metadata.enabled is True
        assert registry.get("alpha").eligible is False
        assert len(registry.list_eligible()) == 0


# ---------------------------------------------------------------------------
# Tests: edge cases and interactions
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases and combined behavior tests."""

    def test_unregister_then_get_all_tools(self):
        t = DummyTool(name="t")
        registry = SkillRegistry()
        registry.register(_make_skill("s", tools=[t]))
        assert len(registry.get_all_tools()) == 1
        registry.unregister("s")
        assert len(registry.get_all_tools()) == 0

    def test_prompt_after_disable(self):
        """Disabling a skill removes it from the prompt."""
        registry = SkillRegistry()
        registry.register(_make_skill("alpha", body="Alpha prompt text"))
        assert "Alpha prompt text" in registry.build_skills_prompt()
        registry.disable_skill("alpha")
        assert registry.build_skills_prompt() == ""

    def test_tools_from_mixed_eligibility(self):
        """Only tools from eligible+enabled skills are returned."""
        t_good = DummyTool(name="good")
        t_disabled = DummyTool(name="disabled")
        t_ineligible = DummyTool(name="ineligible")
        registry = SkillRegistry()
        registry.register(_make_skill("s1", tools=[t_good], eligible=True, enabled=True))
        registry.register(_make_skill("s2", tools=[t_disabled], eligible=True, enabled=False))
        registry.register(_make_skill("s3", tools=[t_ineligible], eligible=False, enabled=True))
        tools = registry.get_all_tools()
        assert len(tools) == 1
        assert tools[0].name == "good"

    def test_registry_isolation(self):
        """Two registries are independent."""
        r1 = SkillRegistry()
        r2 = SkillRegistry()
        r1.register(_make_skill("alpha"))
        assert r1.get("alpha") is not None
        assert r2.get("alpha") is None

    def test_list_eligible_with_inject_false_still_returned(self):
        """list_eligible returns skills regardless of inject_prompt.
        inject_prompt only affects build_skills_prompt."""
        registry = SkillRegistry()
        registry.register(_make_skill("no-inject", inject_prompt=False))
        eligible = registry.list_eligible()
        assert len(eligible) == 1
        assert eligible[0].metadata.name == "no-inject"
