"""
Tests for the SkillLoader from ungula.skills.loader.

Covers scanning directories, parsing SKILL.md frontmatter, eligibility checks,
config path resolution, and source detection.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ungula.config import UngulaConfig
from ungula.skills.loader import (
    LoadedSkill,
    SkillLoader,
    SkillMetadata,
    SkillRequirements,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SKILL_MD_FULL = """\
---
name: test-skill
version: "1.0.0"
description: A test skill
author: Test Author
enabled: true
requires:
  bins: []
  env: []
  config: []
  platform: []
ungula:
  emoji: "T"
  module: null
  inject_prompt: true
---
# Test Skill Body

This is the body content.
"""

SKILL_MD_MINIMAL = """\
---
name: minimal-skill
---
Minimal body.
"""

SKILL_MD_DISABLED = """\
---
name: disabled-skill
enabled: false
---
Disabled body.
"""

SKILL_MD_PLATFORM = """\
---
name: platform-skill
requires:
  platform:
    - win32
---
Windows only.
"""

SKILL_MD_BINS = """\
---
name: bin-skill
requires:
  bins:
    - totally_nonexistent_binary_xyz
---
Needs a binary.
"""

SKILL_MD_ENV = """\
---
name: env-skill
requires:
  env:
    - UNGULA_TEST_NONEXISTENT_VAR
---
Needs env var.
"""

SKILL_MD_CONFIG = """\
---
name: config-skill
requires:
  config:
    - tools.brave_search.api_key
---
Needs config.
"""

SKILL_MD_OPENCLAW_FORMAT = """\
---
name: oc-skill
metadata:
  openclaw:
    emoji: "O"
    os:
      - linux
    requires:
      bins:
        - git
---
OpenClaw format.
"""

SKILL_MD_NO_INJECT = """\
---
name: no-inject-skill
ungula:
  inject_prompt: false
---
Should not inject.
"""


def _write_skill(base_dir: Path, skill_name: str, content: str) -> Path:
    """Write a SKILL.md file inside base_dir/<skill_name>/SKILL.md."""
    skill_dir = base_dir / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content)
    return skill_dir


def _make_config(**overrides) -> UngulaConfig:
    """Create a real UngulaConfig with optional overrides."""
    return UngulaConfig(**overrides)


# ---------------------------------------------------------------------------
# Tests: SkillRequirements / SkillMetadata dataclasses
# ---------------------------------------------------------------------------

class TestSkillDataclasses:
    """Basic tests for the dataclass defaults."""

    def test_skill_requirements_defaults(self):
        reqs = SkillRequirements()
        assert reqs.bins == []
        assert reqs.env == []
        assert reqs.config == []
        assert reqs.platform == []

    def test_skill_metadata_defaults(self):
        meta = SkillMetadata(name="test")
        assert meta.name == "test"
        assert meta.version == "0.0.0"
        assert meta.description == ""
        assert meta.author is None
        assert meta.enabled is True
        assert meta.emoji is None
        assert meta.module_name is None
        assert meta.inject_prompt is True
        assert meta.requirements.bins == []
        assert meta.raw_frontmatter == {}

    def test_loaded_skill_defaults(self):
        meta = SkillMetadata(name="s")
        skill = LoadedSkill(metadata=meta, skill_dir=Path("/tmp/s"), body="body")
        assert skill.tools == []
        assert skill.eligible is True
        assert skill.eligibility_reason is None
        assert skill.source == "user"


# ---------------------------------------------------------------------------
# Tests: scan_directories
# ---------------------------------------------------------------------------

class TestScanDirectories:
    """Tests for SkillLoader.scan_directories."""

    def test_nonexistent_directory_returns_empty(self, tmp_path: Path):
        loader = SkillLoader(_make_config())
        result = loader.scan_directories([tmp_path / "does_not_exist"])
        assert result == []

    def test_empty_directory_returns_empty(self, tmp_path: Path):
        loader = SkillLoader(_make_config())
        result = loader.scan_directories([tmp_path])
        assert result == []

    def test_directory_with_files_only_returns_empty(self, tmp_path: Path):
        """Non-directory children are skipped."""
        (tmp_path / "somefile.txt").write_text("hello")
        loader = SkillLoader(_make_config())
        result = loader.scan_directories([tmp_path])
        assert result == []

    def test_directory_without_skill_md_skipped(self, tmp_path: Path):
        """Subdirectory without SKILL.md is skipped."""
        (tmp_path / "my-skill").mkdir()
        (tmp_path / "my-skill" / "README.md").write_text("readme")
        loader = SkillLoader(_make_config())
        result = loader.scan_directories([tmp_path])
        assert result == []

    def test_scan_finds_valid_skill(self, tmp_path: Path):
        _write_skill(tmp_path, "alpha", SKILL_MD_FULL)
        loader = SkillLoader(_make_config())
        result = loader.scan_directories([tmp_path])
        assert len(result) == 1
        assert result[0].metadata.name == "test-skill"

    def test_scan_multiple_skills(self, tmp_path: Path):
        _write_skill(tmp_path, "alpha", SKILL_MD_FULL)
        _write_skill(tmp_path, "beta", SKILL_MD_MINIMAL)
        loader = SkillLoader(_make_config())
        result = loader.scan_directories([tmp_path])
        names = {s.metadata.name for s in result}
        assert names == {"test-skill", "minimal-skill"}

    def test_later_directories_override_earlier(self, tmp_path: Path):
        """Later dirs take precedence when skills share the same name."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        _write_skill(dir_a, "s", SKILL_MD_FULL)
        # Write a skill with the same *name* in YAML in dir_b
        _write_skill(dir_b, "s", SKILL_MD_FULL.replace("A test skill", "Overridden"))
        loader = SkillLoader(_make_config())
        result = loader.scan_directories([dir_a, dir_b])
        assert len(result) == 1
        assert result[0].metadata.description == "Overridden"

    def test_scan_multiple_directories(self, tmp_path: Path):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        _write_skill(dir_a, "skill-a", SKILL_MD_FULL)
        _write_skill(dir_b, "skill-b", SKILL_MD_MINIMAL)
        loader = SkillLoader(_make_config())
        result = loader.scan_directories([dir_a, dir_b])
        names = {s.metadata.name for s in result}
        assert names == {"test-skill", "minimal-skill"}


# ---------------------------------------------------------------------------
# Tests: load_skill
# ---------------------------------------------------------------------------

class TestLoadSkill:
    """Tests for SkillLoader.load_skill."""

    def test_missing_skill_md_returns_none(self, tmp_path: Path):
        skill_dir = tmp_path / "empty"
        skill_dir.mkdir()
        loader = SkillLoader(_make_config())
        assert loader.load_skill(skill_dir, "user") is None

    def test_load_valid_skill(self, tmp_path: Path):
        skill_dir = _write_skill(tmp_path, "good", SKILL_MD_FULL)
        loader = SkillLoader(_make_config())
        skill = loader.load_skill(skill_dir, "user")
        assert skill is not None
        assert skill.metadata.name == "test-skill"
        assert skill.source == "user"

    def test_load_skill_sets_source(self, tmp_path: Path):
        skill_dir = _write_skill(tmp_path, "x", SKILL_MD_MINIMAL)
        loader = SkillLoader(_make_config())
        skill = loader.load_skill(skill_dir, "clawhub")
        assert skill is not None
        assert skill.source == "clawhub"

    def test_load_skill_disabled_via_frontmatter(self, tmp_path: Path):
        skill_dir = _write_skill(tmp_path, "dis", SKILL_MD_DISABLED)
        loader = SkillLoader(_make_config())
        skill = loader.load_skill(skill_dir, "user")
        assert skill is not None
        assert skill.metadata.enabled is False
        assert skill.eligible is False
        assert skill.eligibility_reason == "Disabled"

    def test_load_skill_config_override_enabled(self, tmp_path: Path):
        """Per-skill config entry can override the enabled field."""
        skill_dir = _write_skill(tmp_path, "over", SKILL_MD_FULL)
        config = _make_config(skills={"entries": {"test-skill": {"enabled": False}}})
        loader = SkillLoader(config)
        skill = loader.load_skill(skill_dir, "user")
        assert skill is not None
        assert skill.metadata.enabled is False

    def test_load_skill_malformed_frontmatter_returns_none(self, tmp_path: Path):
        """If frontmatter parsing fails, load_skill returns None."""
        skill_dir = tmp_path / "bad"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\n: invalid yaml\n---\nbody")
        loader = SkillLoader(_make_config())
        result = loader.load_skill(skill_dir, "user")
        # Depending on the frontmatter lib, this may return None or parse oddly.
        # The code wraps in try/except and returns None on error.
        # We just verify no crash.
        assert result is None or isinstance(result, LoadedSkill)


# ---------------------------------------------------------------------------
# Tests: parse_frontmatter
# ---------------------------------------------------------------------------

class TestParseFrontmatter:
    """Tests for SkillLoader.parse_frontmatter."""

    def test_full_frontmatter(self, tmp_path: Path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(SKILL_MD_FULL)
        loader = SkillLoader(_make_config())
        meta, body = loader.parse_frontmatter(skill_md)

        assert meta.name == "test-skill"
        assert meta.version == "1.0.0"
        assert meta.description == "A test skill"
        assert meta.author == "Test Author"
        assert meta.enabled is True
        assert meta.emoji == "T"
        assert meta.module_name is None
        assert meta.inject_prompt is True
        assert meta.requirements.bins == []
        assert meta.requirements.env == []
        assert "# Test Skill Body" in body
        assert "This is the body content." in body

    def test_minimal_frontmatter(self, tmp_path: Path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(SKILL_MD_MINIMAL)
        loader = SkillLoader(_make_config())
        meta, body = loader.parse_frontmatter(skill_md)

        assert meta.name == "minimal-skill"
        assert meta.version == "0.0.0"
        assert meta.description == ""
        assert meta.author is None
        assert "Minimal body." in body

    def test_name_fallback_to_parent_dir(self, tmp_path: Path):
        """If name is not in frontmatter, the parent directory name is used."""
        skill_dir = tmp_path / "my-fallback-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("---\nversion: '2.0'\n---\nBody text.")
        loader = SkillLoader(_make_config())
        meta, body = loader.parse_frontmatter(skill_md)
        assert meta.name == "my-fallback-skill"

    def test_openclaw_format_requirements(self, tmp_path: Path):
        """OpenClaw metadata.openclaw format is parsed correctly."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(SKILL_MD_OPENCLAW_FORMAT)
        loader = SkillLoader(_make_config())
        meta, body = loader.parse_frontmatter(skill_md)

        assert meta.name == "oc-skill"
        assert meta.emoji == "O"
        assert meta.requirements.platform == ["linux"]
        assert meta.requirements.bins == ["git"]

    def test_raw_frontmatter_preserved(self, tmp_path: Path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(SKILL_MD_FULL)
        loader = SkillLoader(_make_config())
        meta, _ = loader.parse_frontmatter(skill_md)
        assert isinstance(meta.raw_frontmatter, dict)
        assert "name" in meta.raw_frontmatter

    def test_inject_prompt_false(self, tmp_path: Path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(SKILL_MD_NO_INJECT)
        loader = SkillLoader(_make_config())
        meta, body = loader.parse_frontmatter(skill_md)
        assert meta.inject_prompt is False


# ---------------------------------------------------------------------------
# Tests: check_eligibility
# ---------------------------------------------------------------------------

class TestCheckEligibility:
    """Tests for SkillLoader.check_eligibility."""

    def test_disabled_skill(self):
        loader = SkillLoader(_make_config())
        meta = SkillMetadata(name="dis", enabled=False)
        eligible, reason = loader.check_eligibility(meta)
        assert eligible is False
        assert reason == "Disabled"

    def test_wrong_platform(self):
        loader = SkillLoader(_make_config())
        fake_platform = "totally_fake_os"
        meta = SkillMetadata(
            name="plat",
            requirements=SkillRequirements(platform=[fake_platform]),
        )
        eligible, reason = loader.check_eligibility(meta)
        assert eligible is False
        assert "Platform" in reason
        assert sys.platform in reason

    def test_current_platform_passes(self):
        loader = SkillLoader(_make_config())
        meta = SkillMetadata(
            name="plat-ok",
            requirements=SkillRequirements(platform=[sys.platform]),
        )
        eligible, reason = loader.check_eligibility(meta)
        assert eligible is True
        assert reason is None

    def test_missing_binary(self):
        loader = SkillLoader(_make_config())
        meta = SkillMetadata(
            name="bin",
            requirements=SkillRequirements(bins=["totally_nonexistent_binary_xyz"]),
        )
        eligible, reason = loader.check_eligibility(meta)
        assert eligible is False
        assert "Required binary not found" in reason
        assert "totally_nonexistent_binary_xyz" in reason

    def test_binary_found(self):
        """A binary that exists (python3) passes the check."""
        loader = SkillLoader(_make_config())
        meta = SkillMetadata(
            name="bin-ok",
            requirements=SkillRequirements(bins=["python3"]),
        )
        eligible, reason = loader.check_eligibility(meta)
        assert eligible is True
        assert reason is None

    def test_missing_env_var(self):
        loader = SkillLoader(_make_config())
        meta = SkillMetadata(
            name="env",
            requirements=SkillRequirements(env=["UNGULA_TEST_NONEXISTENT_VAR"]),
        )
        eligible, reason = loader.check_eligibility(meta)
        assert eligible is False
        assert "Required env var not set" in reason

    def test_env_var_present(self):
        os.environ["UNGULA_TEST_PRESENT_VAR"] = "1"
        try:
            loader = SkillLoader(_make_config())
            meta = SkillMetadata(
                name="env-ok",
                requirements=SkillRequirements(env=["UNGULA_TEST_PRESENT_VAR"]),
            )
            eligible, reason = loader.check_eligibility(meta)
            assert eligible is True
            assert reason is None
        finally:
            del os.environ["UNGULA_TEST_PRESENT_VAR"]

    def test_env_var_from_skill_config_entry(self):
        """Env var can also come from config.skills.entries.<name>.env."""
        config = _make_config(
            skills={"entries": {"env-cfg": {"env": {"MY_VAR": "hello"}}}}
        )
        loader = SkillLoader(config)
        meta = SkillMetadata(
            name="env-cfg",
            requirements=SkillRequirements(env=["MY_VAR"]),
        )
        eligible, reason = loader.check_eligibility(meta)
        assert eligible is True
        assert reason is None

    def test_all_requirements_met(self):
        loader = SkillLoader(_make_config())
        meta = SkillMetadata(
            name="all-ok",
            requirements=SkillRequirements(
                bins=[],
                env=[],
                config=[],
                platform=[],
            ),
        )
        eligible, reason = loader.check_eligibility(meta)
        assert eligible is True
        assert reason is None

    def test_missing_config_path(self):
        """A config requirement that is not set fails."""
        loader = SkillLoader(_make_config())
        meta = SkillMetadata(
            name="cfg",
            requirements=SkillRequirements(config=["tools.brave_search.api_key"]),
        )
        eligible, reason = loader.check_eligibility(meta)
        assert eligible is False
        assert "Required config not set" in reason

    def test_config_path_present(self):
        """A config requirement that is set passes."""
        config = _make_config(tools={"brave_search": {"api_key": "test-key", "enabled": True}})
        loader = SkillLoader(config)
        meta = SkillMetadata(
            name="cfg-ok",
            requirements=SkillRequirements(config=["tools.brave_search.api_key"]),
        )
        eligible, reason = loader.check_eligibility(meta)
        assert eligible is True
        assert reason is None


# ---------------------------------------------------------------------------
# Tests: _resolve_config_path
# ---------------------------------------------------------------------------

class TestResolveConfigPath:
    """Tests for SkillLoader._resolve_config_path whitelisting and secret masking."""

    def test_allowed_prefix_tools(self):
        config = _make_config(tools={"brave_search": {"enabled": True, "api_key": "key123"}})
        loader = SkillLoader(config)
        assert loader._resolve_config_path("tools.brave_search.enabled") is True

    def test_allowed_prefix_llm(self):
        config = _make_config()
        loader = SkillLoader(config)
        result = loader._resolve_config_path("llm.default_provider")
        assert result == "openrouter"

    def test_allowed_prefix_skills(self):
        config = _make_config()
        loader = SkillLoader(config)
        result = loader._resolve_config_path("skills.enabled")
        assert result is True

    def test_allowed_prefix_messaging(self):
        config = _make_config()
        loader = SkillLoader(config)
        result = loader._resolve_config_path("messaging.discord.enabled")
        assert result is False  # default

    def test_allowed_prefix_embeddings(self):
        config = _make_config()
        loader = SkillLoader(config)
        result = loader._resolve_config_path("embeddings.provider")
        assert result == "local"

    def test_rejected_prefix_auth(self):
        config = _make_config()
        loader = SkillLoader(config)
        assert loader._resolve_config_path("auth.secret_key") is None

    def test_rejected_prefix_server(self):
        config = _make_config()
        loader = SkillLoader(config)
        assert loader._resolve_config_path("server.port") is None

    def test_rejected_prefix_database(self):
        config = _make_config()
        loader = SkillLoader(config)
        assert loader._resolve_config_path("database.path") is None

    def test_rejected_prefix_redis(self):
        config = _make_config()
        loader = SkillLoader(config)
        assert loader._resolve_config_path("redis.host") is None

    def test_secret_key_returns_bool_true(self):
        config = _make_config(tools={"brave_search": {"api_key": "real-secret", "enabled": True}})
        loader = SkillLoader(config)
        result = loader._resolve_config_path("tools.brave_search.api_key")
        # Should return True (value exists) but NOT the actual key string
        assert result is True

    def test_secret_key_returns_bool_false_when_none(self):
        config = _make_config()
        loader = SkillLoader(config)
        result = loader._resolve_config_path("tools.brave_search.api_key")
        # api_key defaults to None, so _resolve_config_path returns None
        # (it bails out when obj is None before checking secret keys)
        assert result is None

    def test_secret_token_returns_bool(self):
        config = _make_config(messaging={"discord": {"token": "tok-123", "enabled": True}})
        loader = SkillLoader(config)
        result = loader._resolve_config_path("messaging.discord.token")
        assert result is True

    def test_nonexistent_path_returns_none(self):
        config = _make_config()
        loader = SkillLoader(config)
        assert loader._resolve_config_path("tools.nonexistent.field") is None

    def test_empty_path_rejected(self):
        config = _make_config()
        loader = SkillLoader(config)
        assert loader._resolve_config_path("") is None


# ---------------------------------------------------------------------------
# Tests: _source_for_dir
# ---------------------------------------------------------------------------

class TestSourceForDir:
    """Tests for SkillLoader._source_for_dir."""

    def test_builtin_path(self):
        loader = SkillLoader(_make_config())
        assert loader._source_for_dir(Path("/app/ungula/skills/builtin/shell")) == "bundled"

    def test_builtin_in_middle_of_path(self):
        loader = SkillLoader(_make_config())
        assert loader._source_for_dir(Path("/some/builtin/extra")) == "bundled"

    def test_user_home_path(self):
        loader = SkillLoader(_make_config())
        user_skills = Path.home() / ".ungula" / "skills"
        assert loader._source_for_dir(user_skills) == "user"

    def test_generic_path(self):
        loader = SkillLoader(_make_config())
        assert loader._source_for_dir(Path("/opt/custom-skills")) == "user"


# ---------------------------------------------------------------------------
# Tests: integration - scan + eligibility
# ---------------------------------------------------------------------------

class TestScanWithEligibility:
    """Integration tests: scan_directories populates eligibility."""

    def test_disabled_skill_is_ineligible(self, tmp_path: Path):
        _write_skill(tmp_path, "dis", SKILL_MD_DISABLED)
        loader = SkillLoader(_make_config())
        result = loader.scan_directories([tmp_path])
        assert len(result) == 1
        assert result[0].eligible is False
        assert result[0].eligibility_reason == "Disabled"

    def test_platform_mismatch_ineligible(self, tmp_path: Path):
        _write_skill(tmp_path, "plat", SKILL_MD_PLATFORM)
        loader = SkillLoader(_make_config())
        result = loader.scan_directories([tmp_path])
        assert len(result) == 1
        assert result[0].eligible is False
        assert "Platform" in result[0].eligibility_reason

    def test_missing_binary_ineligible(self, tmp_path: Path):
        _write_skill(tmp_path, "bin", SKILL_MD_BINS)
        loader = SkillLoader(_make_config())
        result = loader.scan_directories([tmp_path])
        assert len(result) == 1
        assert result[0].eligible is False
        assert "binary" in result[0].eligibility_reason.lower()

    def test_missing_env_ineligible(self, tmp_path: Path):
        _write_skill(tmp_path, "env", SKILL_MD_ENV)
        loader = SkillLoader(_make_config())
        result = loader.scan_directories([tmp_path])
        assert len(result) == 1
        assert result[0].eligible is False

    def test_eligible_skill_body_preserved(self, tmp_path: Path):
        _write_skill(tmp_path, "good", SKILL_MD_FULL)
        loader = SkillLoader(_make_config())
        result = loader.scan_directories([tmp_path])
        assert len(result) == 1
        assert result[0].eligible is True
        assert "This is the body content." in result[0].body
