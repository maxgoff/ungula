"""
Tests for modular prompt sections and the PromptBuilder.

Covers PromptMode enum, individual section classes, priority ordering,
PromptBuilder composition, and the build_prompt_from_workspace convenience
function.
"""

import tempfile
from pathlib import Path
from typing import Generator

import pytest

from ungula.agents.prompt_sections import (
    AgentsSection,
    IdentitySection,
    MemorySection,
    PromptBuilder,
    PromptMode,
    PromptSection,
    RuntimeSection,
    SafetySection,
    SkillsSection,
    ToolsSection,
    UserSection,
    build_prompt_from_workspace,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace_dir() -> Generator[Path, None, None]:
    """Create a temporary workspace directory for section tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def populated_workspace(workspace_dir: Path) -> Path:
    """Create a workspace with all standard files populated."""
    (workspace_dir / "SOUL.md").write_text("You are a helpful assistant named Ungula.")
    (workspace_dir / "IDENTITY.md").write_text("Agent identity: Ungula v1.0")
    (workspace_dir / "USER.md").write_text("The user prefers concise answers.")
    (workspace_dir / "AGENTS.md").write_text("## Agent Configuration\n\nDefault agent settings.")
    return workspace_dir


# ===========================================================================
# PromptMode
# ===========================================================================


class TestPromptMode:
    """Tests for the PromptMode enum."""

    def test_full_value(self):
        assert PromptMode.FULL.value == "full"

    def test_minimal_value(self):
        assert PromptMode.MINIMAL.value == "minimal"

    def test_none_value(self):
        assert PromptMode.NONE.value == "none"

    def test_enum_from_string(self):
        assert PromptMode("full") == PromptMode.FULL
        assert PromptMode("minimal") == PromptMode.MINIMAL
        assert PromptMode("none") == PromptMode.NONE

    def test_enum_is_str(self):
        """PromptMode extends str, so it should be usable as a string."""
        assert isinstance(PromptMode.FULL, str)
        assert PromptMode.FULL == "full"

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            PromptMode("invalid")


# ===========================================================================
# IdentitySection
# ===========================================================================


class TestIdentitySection:
    """Tests for IdentitySection."""

    def test_renders_soul_and_identity(self, populated_workspace: Path):
        section = IdentitySection(populated_workspace)
        result = section.render()
        assert result is not None
        assert "helpful assistant" in result
        assert "Ungula v1.0" in result

    def test_renders_soul_only(self, workspace_dir: Path):
        (workspace_dir / "SOUL.md").write_text("Soul content only.")
        section = IdentitySection(workspace_dir)
        result = section.render()
        assert result == "Soul content only."

    def test_renders_identity_only(self, workspace_dir: Path):
        (workspace_dir / "IDENTITY.md").write_text("Identity content only.")
        section = IdentitySection(workspace_dir)
        result = section.render()
        assert result == "Identity content only."

    def test_returns_none_when_no_files(self, workspace_dir: Path):
        section = IdentitySection(workspace_dir)
        result = section.render()
        assert result is None

    def test_returns_none_when_files_empty(self, workspace_dir: Path):
        (workspace_dir / "SOUL.md").write_text("")
        (workspace_dir / "IDENTITY.md").write_text("   ")
        section = IdentitySection(workspace_dir)
        result = section.render()
        assert result is None

    def test_priority_is_10(self, workspace_dir: Path):
        section = IdentitySection(workspace_dir)
        assert section.priority == 10

    def test_active_in_full_and_minimal(self, workspace_dir: Path):
        section = IdentitySection(workspace_dir)
        assert section.is_active(PromptMode.FULL)
        assert section.is_active(PromptMode.MINIMAL)
        assert not section.is_active(PromptMode.NONE)


# ===========================================================================
# SafetySection
# ===========================================================================


class TestSafetySection:
    """Tests for SafetySection."""

    def test_renders_safety_guidelines(self):
        section = SafetySection()
        result = section.render()
        assert result is not None
        assert "Safety Guidelines" in result
        assert "API keys" in result
        assert "untrusted" in result

    def test_priority_is_15(self):
        section = SafetySection()
        assert section.priority == 15

    def test_active_in_full_and_minimal(self):
        section = SafetySection()
        assert section.is_active(PromptMode.FULL)
        assert section.is_active(PromptMode.MINIMAL)
        assert not section.is_active(PromptMode.NONE)

    def test_render_is_deterministic(self):
        section = SafetySection()
        assert section.render() == section.render()


# ===========================================================================
# UserSection
# ===========================================================================


class TestUserSection:
    """Tests for UserSection."""

    def test_renders_user_file(self, populated_workspace: Path):
        section = UserSection(populated_workspace)
        result = section.render()
        assert result is not None
        assert "concise answers" in result

    def test_returns_none_when_no_file(self, workspace_dir: Path):
        section = UserSection(workspace_dir)
        assert section.render() is None

    def test_returns_none_when_file_empty(self, workspace_dir: Path):
        (workspace_dir / "USER.md").write_text("   ")
        section = UserSection(workspace_dir)
        assert section.render() is None

    def test_priority_is_20(self, workspace_dir: Path):
        section = UserSection(workspace_dir)
        assert section.priority == 20

    def test_active_only_in_full(self, workspace_dir: Path):
        section = UserSection(workspace_dir)
        assert section.is_active(PromptMode.FULL)
        assert not section.is_active(PromptMode.MINIMAL)
        assert not section.is_active(PromptMode.NONE)


# ===========================================================================
# AgentsSection
# ===========================================================================


class TestAgentsSection:
    """Tests for AgentsSection."""

    def test_renders_agents_file(self, populated_workspace: Path):
        section = AgentsSection(populated_workspace)
        result = section.render()
        assert result is not None
        assert "Agent Configuration" in result

    def test_returns_none_when_no_file(self, workspace_dir: Path):
        section = AgentsSection(workspace_dir)
        assert section.render() is None

    def test_priority_is_25(self, workspace_dir: Path):
        section = AgentsSection(workspace_dir)
        assert section.priority == 25

    def test_active_only_in_full(self, workspace_dir: Path):
        section = AgentsSection(workspace_dir)
        assert section.is_active(PromptMode.FULL)
        assert not section.is_active(PromptMode.MINIMAL)


# ===========================================================================
# ToolsSection
# ===========================================================================


class TestToolsSection:
    """Tests for ToolsSection."""

    def test_renders_tools_info(self):
        tools = [
            {"name": "shell_exec", "description": "Run shell commands"},
            {"name": "file_read", "description": "Read a file"},
        ]
        section = ToolsSection(tools_info=tools)
        result = section.render()
        assert result is not None
        assert "Available Tools" in result
        assert "shell_exec" in result
        assert "file_read" in result
        assert "Run shell commands" in result

    def test_returns_none_when_no_tools(self):
        section = ToolsSection(tools_info=None)
        assert section.render() is None

    def test_returns_none_when_empty_tools(self):
        section = ToolsSection(tools_info=[])
        assert section.render() is None

    def test_handles_missing_description(self):
        tools = [{"name": "my_tool"}]
        section = ToolsSection(tools_info=tools)
        result = section.render()
        assert result is not None
        assert "my_tool" in result

    def test_handles_missing_name(self):
        tools = [{"description": "Does something"}]
        section = ToolsSection(tools_info=tools)
        result = section.render()
        assert result is not None
        assert "unknown" in result

    def test_priority_is_30(self):
        section = ToolsSection()
        assert section.priority == 30

    def test_active_only_in_full(self):
        section = ToolsSection()
        assert section.is_active(PromptMode.FULL)
        assert not section.is_active(PromptMode.MINIMAL)


# ===========================================================================
# SkillsSection
# ===========================================================================


class TestSkillsSection:
    """Tests for SkillsSection."""

    def test_renders_skills_prompt(self):
        section = SkillsSection(skills_prompt="Use /search to look things up.")
        result = section.render()
        assert result is not None
        assert "Available Skills" in result
        assert "/search" in result

    def test_returns_none_when_no_skills(self):
        section = SkillsSection(skills_prompt=None)
        assert section.render() is None

    def test_returns_none_when_empty_skills(self):
        section = SkillsSection(skills_prompt="")
        assert section.render() is None

    def test_priority_is_35(self):
        section = SkillsSection()
        assert section.priority == 35

    def test_active_only_in_full(self):
        section = SkillsSection()
        assert section.is_active(PromptMode.FULL)
        assert not section.is_active(PromptMode.MINIMAL)


# ===========================================================================
# MemorySection
# ===========================================================================


class TestMemorySection:
    """Tests for MemorySection."""

    def test_renders_memory_context(self):
        memories = [
            "User prefers Python over JavaScript.",
            "Previous project used FastAPI.",
        ]
        section = MemorySection(memory_context=memories)
        result = section.render()
        assert result is not None
        assert "Relevant Memory" in result
        assert "1. User prefers Python" in result
        assert "2. Previous project used FastAPI" in result

    def test_returns_none_when_no_memory(self):
        section = MemorySection(memory_context=None)
        assert section.render() is None

    def test_returns_none_when_empty_memory(self):
        section = MemorySection(memory_context=[])
        assert section.render() is None

    def test_priority_is_40(self):
        section = MemorySection()
        assert section.priority == 40

    def test_active_only_in_full(self):
        section = MemorySection()
        assert section.is_active(PromptMode.FULL)
        assert not section.is_active(PromptMode.MINIMAL)


# ===========================================================================
# RuntimeSection
# ===========================================================================


class TestRuntimeSection:
    """Tests for RuntimeSection."""

    def test_renders_runtime_context(self):
        section = RuntimeSection()
        result = section.render()
        assert result is not None
        assert "Runtime Context" in result
        assert "Current time" in result
        assert "Current date" in result
        assert "UTC" in result

    def test_contains_date_format(self):
        section = RuntimeSection()
        result = section.render()
        # Should contain YYYY-MM-DD format
        import re
        assert re.search(r"\d{4}-\d{2}-\d{2}", result)

    def test_priority_is_90(self):
        section = RuntimeSection()
        assert section.priority == 90

    def test_active_in_full_and_minimal(self):
        section = RuntimeSection()
        assert section.is_active(PromptMode.FULL)
        assert section.is_active(PromptMode.MINIMAL)
        assert not section.is_active(PromptMode.NONE)


# ===========================================================================
# Section priority ordering
# ===========================================================================


class TestSectionPriority:
    """Tests that section priorities are correctly ordered."""

    def test_identity_before_safety(self, workspace_dir: Path):
        identity = IdentitySection(workspace_dir)
        safety = SafetySection()
        assert identity.priority < safety.priority

    def test_safety_before_user(self, workspace_dir: Path):
        safety = SafetySection()
        user = UserSection(workspace_dir)
        assert safety.priority < user.priority

    def test_user_before_agents(self, workspace_dir: Path):
        user = UserSection(workspace_dir)
        agents = AgentsSection(workspace_dir)
        assert user.priority < agents.priority

    def test_agents_before_tools(self, workspace_dir: Path):
        agents = AgentsSection(workspace_dir)
        tools = ToolsSection()
        assert agents.priority < tools.priority

    def test_tools_before_skills(self):
        tools = ToolsSection()
        skills = SkillsSection()
        assert tools.priority < skills.priority

    def test_skills_before_memory(self):
        skills = SkillsSection()
        memory = MemorySection()
        assert skills.priority < memory.priority

    def test_memory_before_runtime(self):
        memory = MemorySection()
        runtime = RuntimeSection()
        assert memory.priority < runtime.priority

    def test_full_ordering(self, workspace_dir: Path):
        """Verify the complete priority ordering from first to last."""
        sections = [
            IdentitySection(workspace_dir),
            SafetySection(),
            UserSection(workspace_dir),
            AgentsSection(workspace_dir),
            ToolsSection(),
            SkillsSection(),
            MemorySection(),
            RuntimeSection(),
        ]
        priorities = [s.priority for s in sections]
        assert priorities == sorted(priorities), "Sections are not in priority order"


# ===========================================================================
# PromptSection base class
# ===========================================================================


class TestPromptSectionBase:
    """Tests for the abstract PromptSection base class."""

    def test_default_modes(self):
        """Default modes should include FULL and MINIMAL."""

        class ConcreteSection(PromptSection):
            def render(self) -> str | None:
                return "content"

        section = ConcreteSection()
        assert section.is_active(PromptMode.FULL)
        assert section.is_active(PromptMode.MINIMAL)
        assert not section.is_active(PromptMode.NONE)

    def test_custom_modes(self):
        class ConcreteSection(PromptSection):
            def render(self) -> str | None:
                return "content"

        section = ConcreteSection(modes={PromptMode.FULL})
        assert section.is_active(PromptMode.FULL)
        assert not section.is_active(PromptMode.MINIMAL)

    def test_custom_priority(self):
        class ConcreteSection(PromptSection):
            def render(self) -> str | None:
                return "content"

        section = ConcreteSection(priority=99)
        assert section.priority == 99


# ===========================================================================
# PromptBuilder
# ===========================================================================


class TestPromptBuilder:
    """Tests for the PromptBuilder class."""

    def test_build_full_mode(self, populated_workspace: Path):
        builder = PromptBuilder(mode=PromptMode.FULL)
        builder.add_section(IdentitySection(populated_workspace))
        builder.add_section(SafetySection())
        builder.add_section(RuntimeSection())

        result = builder.build()
        assert "helpful assistant" in result
        assert "Safety Guidelines" in result
        assert "Runtime Context" in result

    def test_build_minimal_mode(self, populated_workspace: Path):
        builder = PromptBuilder(mode=PromptMode.MINIMAL)
        builder.add_section(IdentitySection(populated_workspace))
        builder.add_section(SafetySection())
        builder.add_section(UserSection(populated_workspace))  # FULL only
        builder.add_section(RuntimeSection())

        result = builder.build()
        assert "helpful assistant" in result
        assert "Safety Guidelines" in result
        assert "Runtime Context" in result
        # User section should NOT be included in minimal mode
        assert "concise answers" not in result

    def test_build_none_mode_returns_empty(self, populated_workspace: Path):
        builder = PromptBuilder(mode=PromptMode.NONE)
        builder.add_section(IdentitySection(populated_workspace))
        builder.add_section(SafetySection())

        result = builder.build()
        assert result == ""

    def test_sections_sorted_by_priority(self, populated_workspace: Path):
        builder = PromptBuilder(mode=PromptMode.FULL)
        # Add in reverse priority order
        builder.add_section(RuntimeSection())  # priority 90
        builder.add_section(SafetySection())   # priority 15
        builder.add_section(IdentitySection(populated_workspace))  # priority 10

        result = builder.build()
        # Identity (10) should appear before Safety (15) before Runtime (90)
        identity_pos = result.find("Ungula")
        safety_pos = result.find("Safety Guidelines")
        runtime_pos = result.find("Runtime Context")
        assert identity_pos < safety_pos < runtime_pos

    def test_sections_with_none_render_are_skipped(self, workspace_dir: Path):
        builder = PromptBuilder(mode=PromptMode.FULL)
        builder.add_section(SafetySection())
        builder.add_section(IdentitySection(workspace_dir))  # No files, renders None
        builder.add_section(UserSection(workspace_dir))       # No files, renders None

        result = builder.build()
        assert "Safety Guidelines" in result
        # Should only have safety content, no separators for empty sections
        assert result.count("---") == 0  # Only one section, no separators

    def test_separator_between_sections(self, populated_workspace: Path):
        builder = PromptBuilder(mode=PromptMode.FULL)
        builder.add_section(IdentitySection(populated_workspace))
        builder.add_section(SafetySection())

        result = builder.build()
        assert "---" in result

    def test_add_section_returns_self(self, workspace_dir: Path):
        builder = PromptBuilder()
        result = builder.add_section(SafetySection())
        assert result is builder

    def test_chaining(self, workspace_dir: Path):
        """add_section should support chaining."""
        builder = (
            PromptBuilder()
            .add_section(SafetySection())
            .add_section(RuntimeSection())
        )
        result = builder.build()
        assert "Safety Guidelines" in result
        assert "Runtime Context" in result

    def test_empty_builder(self):
        builder = PromptBuilder()
        result = builder.build()
        assert result == ""

    def test_all_full_only_sections_excluded_in_minimal(self, populated_workspace: Path):
        """In minimal mode, FULL-only sections should all be excluded."""
        builder = PromptBuilder(mode=PromptMode.MINIMAL)
        builder.add_section(UserSection(populated_workspace))
        builder.add_section(AgentsSection(populated_workspace))
        builder.add_section(ToolsSection([{"name": "t", "description": "d"}]))
        builder.add_section(SkillsSection("skill text"))
        builder.add_section(MemorySection(["memory text"]))

        result = builder.build()
        # All of these are FULL-only, so minimal should produce nothing
        assert result == ""


# ===========================================================================
# build_prompt_from_workspace
# ===========================================================================


class TestBuildPromptFromWorkspace:
    """Tests for the convenience function build_prompt_from_workspace."""

    def test_full_mode_includes_all_sections(self, populated_workspace: Path):
        result = build_prompt_from_workspace(
            workspace_dir=populated_workspace,
            mode=PromptMode.FULL,
            skills_prompt="Available: /search",
            tools_info=[{"name": "shell", "description": "Run commands"}],
            memory_context=["User likes Python"],
        )
        assert "helpful assistant" in result       # Identity
        assert "Safety Guidelines" in result       # Safety
        assert "concise answers" in result          # User
        assert "Agent Configuration" in result      # Agents
        assert "shell" in result                    # Tools
        assert "/search" in result                  # Skills
        assert "User likes Python" in result        # Memory
        assert "Runtime Context" in result          # Runtime

    def test_minimal_mode_excludes_full_sections(self, populated_workspace: Path):
        result = build_prompt_from_workspace(
            workspace_dir=populated_workspace,
            mode=PromptMode.MINIMAL,
            skills_prompt="skill info",
            tools_info=[{"name": "tool", "description": "d"}],
            memory_context=["memory"],
        )
        # Minimal includes: Identity, Safety, Runtime
        assert "helpful assistant" in result
        assert "Safety Guidelines" in result
        assert "Runtime Context" in result
        # Minimal excludes: User, Agents, Tools, Skills, Memory
        assert "concise answers" not in result
        assert "skill info" not in result
        assert "memory" not in result

    def test_none_mode_returns_empty(self, populated_workspace: Path):
        result = build_prompt_from_workspace(
            workspace_dir=populated_workspace,
            mode=PromptMode.NONE,
        )
        assert result == ""

    def test_defaults_to_full_mode(self, populated_workspace: Path):
        result = build_prompt_from_workspace(workspace_dir=populated_workspace)
        # Should include identity and safety at minimum
        assert "helpful assistant" in result
        assert "Safety Guidelines" in result

    def test_empty_workspace(self, workspace_dir: Path):
        """With no workspace files and no optional args, only safety + runtime."""
        result = build_prompt_from_workspace(workspace_dir=workspace_dir)
        assert "Safety Guidelines" in result
        assert "Runtime Context" in result

    def test_no_optional_args(self, populated_workspace: Path):
        """Calling without skills, tools, memory should still work."""
        result = build_prompt_from_workspace(workspace_dir=populated_workspace)
        assert "helpful assistant" in result
        assert "Available Tools" not in result
        assert "Available Skills" not in result
        assert "Relevant Memory" not in result

    def test_only_skills_prompt(self, workspace_dir: Path):
        result = build_prompt_from_workspace(
            workspace_dir=workspace_dir,
            skills_prompt="Use /help for assistance.",
        )
        assert "Available Skills" in result
        assert "/help" in result

    def test_only_tools_info(self, workspace_dir: Path):
        result = build_prompt_from_workspace(
            workspace_dir=workspace_dir,
            tools_info=[{"name": "calculator", "description": "Do math"}],
        )
        assert "Available Tools" in result
        assert "calculator" in result

    def test_only_memory_context(self, workspace_dir: Path):
        result = build_prompt_from_workspace(
            workspace_dir=workspace_dir,
            memory_context=["The user is a Python developer."],
        )
        assert "Relevant Memory" in result
        assert "Python developer" in result
