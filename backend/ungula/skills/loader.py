"""
Skill loading, parsing, and registry.

Handles scanning directories for SKILL.md files, parsing YAML frontmatter,
checking eligibility, loading optional Python tool modules, and managing
the skill lifecycle.
"""

import importlib.util
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import frontmatter

from ..config import UngulaConfig
from ..tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


@dataclass
class SkillRequirements:
    """Requirements that must be met for a skill to be eligible."""

    bins: list[str] = field(default_factory=list)
    env: list[str] = field(default_factory=list)
    config: list[str] = field(default_factory=list)
    platform: list[str] = field(default_factory=list)


@dataclass
class SkillMetadata:
    """Parsed metadata from a SKILL.md frontmatter."""

    name: str
    version: str = "0.0.0"
    description: str = ""
    author: str | None = None
    homepage: str | None = None
    enabled: bool = True
    emoji: str | None = None
    module_name: str | None = None  # ungula.module -- Python file with Tool subclasses
    inject_prompt: bool = True  # ungula.inject_prompt
    requirements: SkillRequirements = field(default_factory=SkillRequirements)
    raw_frontmatter: dict[str, Any] = field(default_factory=dict)


@dataclass
class LoadedSkill:
    """A fully loaded skill with metadata, body, tools, and eligibility status."""

    metadata: SkillMetadata
    skill_dir: Path
    body: str  # Markdown body (post-frontmatter)
    tools: list[Tool] = field(default_factory=list)
    eligible: bool = True
    eligibility_reason: str | None = None
    source: str = "user"  # "bundled", "user", "clawhub"


class SkillLoader:
    """Loads skills from directories, parses SKILL.md, checks eligibility."""

    def __init__(self, config: UngulaConfig):
        self.config = config

    def scan_directories(self, dirs: list[Path]) -> list[LoadedSkill]:
        """Scan directories for skills, parse SKILL.md, check eligibility.

        Later directories take precedence (override earlier ones by name).
        """
        merged: dict[str, LoadedSkill] = {}

        for directory in dirs:
            if not directory.exists():
                logger.debug("Skill directory does not exist: %s", directory)
                continue

            source = self._source_for_dir(directory)

            for child in sorted(directory.iterdir()):
                if not child.is_dir():
                    continue
                skill_md = child / "SKILL.md"
                if not skill_md.exists():
                    continue

                skill = self.load_skill(child, source)
                if skill:
                    merged[skill.metadata.name] = skill

        return list(merged.values())

    def load_skill(self, skill_dir: Path, source: str) -> LoadedSkill | None:
        """Load a single skill from a directory."""
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return None

        try:
            metadata, body = self.parse_frontmatter(skill_md)
        except Exception as e:
            logger.warning("Failed to parse SKILL.md in %s: %s", skill_dir, e)
            return None

        # Check per-skill config override for enabled
        skill_entry = self.config.skills.entries.get(metadata.name, {})
        if skill_entry.get("enabled") is not None:
            metadata.enabled = skill_entry["enabled"]

        # Check eligibility
        eligible, reason = self.check_eligibility(metadata)

        # Load Python tools if module specified and eligible
        tools: list[Tool] = []
        tools_note: str | None = None
        if metadata.module_name and eligible and metadata.enabled:
            tools = self.load_tools_from_module(skill_dir, metadata.module_name)
            if not tools:
                tools_note = "Tool module loaded but no tools registered (check config)"

        # If skill has a module but tools didn't load, surface that
        if reason is None and tools_note:
            reason = tools_note

        return LoadedSkill(
            metadata=metadata,
            skill_dir=skill_dir,
            body=body,
            tools=tools,
            eligible=eligible,
            eligibility_reason=reason,
            source=source,
        )

    def parse_frontmatter(self, skill_md_path: Path) -> tuple[SkillMetadata, str]:
        """Parse SKILL.md frontmatter and body."""
        post = frontmatter.load(str(skill_md_path))
        fm = dict(post.metadata)
        body = post.content

        # Parse requirements from both Ungula-native and OpenClaw formats
        requirements = self._parse_requirements(fm)

        # Parse ungula-specific extensions
        ungula = fm.get("ungula", {})

        metadata = SkillMetadata(
            name=fm.get("name", skill_md_path.parent.name),
            version=str(fm.get("version", "0.0.0")),
            description=fm.get("description", ""),
            author=fm.get("author"),
            homepage=fm.get("homepage"),
            enabled=fm.get("enabled", True),
            emoji=ungula.get("emoji") or fm.get("metadata", {}).get("openclaw", {}).get("emoji"),
            module_name=ungula.get("module"),
            inject_prompt=ungula.get("inject_prompt", True),
            requirements=requirements,
            raw_frontmatter=fm,
        )

        return metadata, body

    def _parse_requirements(self, fm: dict[str, Any]) -> SkillRequirements:
        """Parse requirements from frontmatter, handling both Ungula and OpenClaw formats."""
        # Try Ungula-native format first
        requires = fm.get("requires", {})
        if requires:
            return SkillRequirements(
                bins=requires.get("bins", []),
                env=requires.get("env", []),
                config=requires.get("config", []),
                platform=requires.get("platform", []),
            )

        # Fall back to OpenClaw metadata format
        openclaw = fm.get("metadata", {}).get("openclaw", {})
        oc_requires = openclaw.get("requires", {})
        return SkillRequirements(
            bins=oc_requires.get("bins", []),
            env=oc_requires.get("env", []),
            config=oc_requires.get("config", []),
            platform=openclaw.get("os", []),
        )

    def check_eligibility(self, metadata: SkillMetadata) -> tuple[bool, str | None]:
        """Check if skill requirements are met.

        Returns:
            Tuple of (eligible, reason). reason is None if eligible.
        """
        if not metadata.enabled:
            return False, "Disabled"

        reqs = metadata.requirements

        # Check platform
        if reqs.platform:
            current = sys.platform
            if current not in reqs.platform:
                return False, f"Platform {current} not supported (requires {reqs.platform})"

        # Check binaries
        for bin_name in reqs.bins:
            if shutil.which(bin_name) is None:
                return False, f"Required binary not found: {bin_name}"

        # Check environment variables
        for env_var in reqs.env:
            if not os.environ.get(env_var):
                # Also check skill-specific config
                skill_config = self.config.skills.entries.get(metadata.name, {})
                skill_env = skill_config.get("env", {})
                if not skill_env.get(env_var):
                    return False, f"Required env var not set: {env_var}"

        # Check config paths
        for config_path in reqs.config:
            if not self._resolve_config_path(config_path):
                return False, f"Required config not set: {config_path}"

        return True, None

    # Config paths that skills are allowed to check for eligibility
    _ALLOWED_CONFIG_PREFIXES = frozenset({
        "tools.", "skills.", "llm.", "messaging.", "embeddings.",
    })
    # Config keys whose values should not be exposed (return bool instead)
    _SECRET_CONFIG_KEYS = frozenset({
        "api_key", "token", "password", "secret_key", "secret",
    })

    def _resolve_config_path(self, path: str) -> Any:
        """Resolve a dot-notation config path (e.g. 'tools.brave_search.api_key').

        Only whitelisted config prefixes are accessible.
        Secret values return True/False instead of the actual value.
        """
        # Whitelist check
        if not any(path.startswith(prefix) for prefix in self._ALLOWED_CONFIG_PREFIXES):
            return None

        parts = path.split(".")
        obj: Any = self.config
        for part in parts:
            if isinstance(obj, dict):
                obj = obj.get(part)
            elif hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                return None
            if obj is None:
                return None

        # Don't expose actual secret values -- return bool
        if parts[-1] in self._SECRET_CONFIG_KEYS:
            return bool(obj)

        return obj

    def load_tools_from_module(self, skill_dir: Path, module_name: str) -> list[Tool]:
        """Dynamically load Tool subclasses from a Python module in the skill directory."""
        module_path = skill_dir / f"{module_name}.py"
        if not module_path.exists():
            logger.warning("Skill module not found: %s", module_path)
            return []

        try:
            spec = importlib.util.spec_from_file_location(
                f"ungula.skills.dynamic.{skill_dir.name}.{module_name}",
                module_path,
            )
            if spec is None or spec.loader is None:
                logger.warning("Could not create module spec for: %s", module_path)
                return []

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            tools = []
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, Tool) and attr is not Tool:
                    tool_instance = self._instantiate_tool(attr, skill_dir)
                    if tool_instance:
                        tools.append(tool_instance)

            logger.debug("Loaded %d tools from %s", len(tools), module_path)
            return tools

        except Exception as e:
            logger.warning("Failed to load skill module %s: %s", module_path, e)
            return []

    def _instantiate_tool(self, tool_class: type[Tool], skill_dir: Path) -> Tool | None:
        """Instantiate a Tool subclass, injecting config where needed."""
        # Special handling for known built-in tools that need config
        tool_name = getattr(tool_class, "name", tool_class.__name__)

        if tool_name == "web_search":
            from ..tools.web_search import BraveSearchConfig, TavilySearchConfig
            brave_config = self.config.tools.brave_search
            tavily_config = self.config.tools.tavily_search
            if brave_config.enabled and brave_config.api_key:
                # Build Tavily fallback config if available
                tavily_fallback = None
                if tavily_config.enabled and tavily_config.api_key:
                    tavily_fallback = TavilySearchConfig(
                        api_key=tavily_config.api_key,
                        max_results=tavily_config.max_results,
                    )
                    logger.info("Tavily Search configured as fallback provider")
                return tool_class(
                    BraveSearchConfig(
                        api_key=brave_config.api_key,
                        max_results=brave_config.max_results,
                    ),
                    tavily_config=tavily_fallback,
                )
            logger.info("Skipping web_search tool: Brave Search not configured")
            return None

        if tool_name == "shell_exec":
            shell_config = self.config.skills.shell
            if not shell_config.enabled:
                logger.info("Skipping shell_exec tool: disabled in config")
                return None
            return tool_class(shell_config)

        # File tools need workspace_dir and config
        if tool_name in ("file_read", "file_write", "file_edit", "file_search"):
            from ..config import get_workspace_dir
            file_config = self.config.file_tools
            if not file_config.enabled:
                logger.info("Skipping %s tool: file tools disabled", tool_name)
                return None
            return tool_class(get_workspace_dir(), file_config)

        # Process tools need ProcessManager and config
        if tool_name in ("process_exec", "process_manage"):
            process_config = self.config.process_tools
            if not process_config.enabled:
                logger.info("Skipping %s tool: process tools disabled", tool_name)
                return None
            # Get or create shared ProcessManager
            if not hasattr(self, "_process_manager"):
                from ..skills.builtin.process.manager import ProcessManager
                self._process_manager = ProcessManager(
                    max_concurrent=process_config.max_background,
                    max_output_size=process_config.max_output_size,
                )
            return tool_class(self._process_manager, process_config)

        # Node invoke tool needs NodeManager
        if tool_name == "node_invoke":
            # NodeManager is injected later via main.py; skip at load time
            # and register manually after NodeManager is created
            logger.info("Skipping node_invoke at skill load time (needs NodeManager)")
            return None

        # Workspace write tool needs workspace_dir
        if tool_name == "workspace_write":
            from ..config import get_workspace_dir
            return tool_class(get_workspace_dir())

        # Browser tool needs BrowserManager
        if tool_name == "browser":
            browser_config = self.config.browser
            if not browser_config.enabled:
                logger.info("Skipping browser tool: disabled in config")
                return None
            try:
                from ..browser.manager import BrowserManager
                if not hasattr(self, "_browser_manager"):
                    self._browser_manager = BrowserManager(
                        headless=browser_config.headless,
                        timeout=browser_config.timeout,
                        max_tabs=browser_config.max_tabs,
                    )
                return tool_class(self._browser_manager)
            except ImportError:
                logger.info("Skipping browser tool: playwright not installed")
                return None

        # Image processing tool needs workspace_dir
        if tool_name == "image_process":
            from ..config import get_workspace_dir
            return tool_class(get_workspace_dir())

        # Default: try no-arg constructor
        try:
            return tool_class()
        except TypeError as e:
            logger.warning("Could not instantiate tool %s: %s", tool_name, e)
            return None

    def _source_for_dir(self, directory: Path) -> str:
        """Determine the source label for a skill directory."""
        dir_str = str(directory)
        if "builtin" in dir_str:
            return "bundled"
        ungula_home = str(Path.home() / ".ungula")
        if dir_str.startswith(ungula_home):
            return "user"
        return "user"


class SkillRegistry:
    """Registry for managing loaded skills."""

    def __init__(self):
        self._skills: dict[str, LoadedSkill] = {}

    def register(self, skill: LoadedSkill) -> None:
        """Register a loaded skill."""
        self._skills[skill.metadata.name] = skill
        logger.debug("Registered skill: %s (%s)", skill.metadata.name, skill.source)

    def unregister(self, name: str) -> None:
        """Unregister a skill by name."""
        self._skills.pop(name, None)

    def get(self, name: str) -> LoadedSkill | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> list[LoadedSkill]:
        """List all registered skills."""
        return list(self._skills.values())

    def list_eligible(self) -> list[LoadedSkill]:
        """List only eligible and enabled skills."""
        return [s for s in self._skills.values() if s.eligible and s.metadata.enabled]

    def get_all_tools(self) -> list[Tool]:
        """Get all tools from all eligible skills."""
        tools = []
        for skill in self.list_eligible():
            tools.extend(skill.tools)
        return tools

    def build_skills_prompt(self) -> str:
        """Build the skills section for the system prompt.

        Concatenates the markdown body of all eligible skills that
        have inject_prompt=True. Includes skill directory path so
        the agent knows where to run commands from.
        """
        sections = []
        for skill in self.list_eligible():
            if skill.metadata.inject_prompt and skill.body.strip():
                header = f"### {skill.metadata.name}"
                if skill.metadata.description:
                    header += f" -- {skill.metadata.description}"
                # Include skill directory so agent knows where to run commands
                location = f"\n\n**Skill location:** `{skill.skill_dir}`"
                sections.append(f"{header}{location}\n\n{skill.body.strip()}")

        if not sections:
            return ""

        return "\n\n---\n\n".join(sections)

    def enable_skill(self, name: str) -> bool:
        """Enable a skill by name. Returns True if found."""
        skill = self._skills.get(name)
        if skill:
            skill.metadata.enabled = True
            return True
        return False

    def disable_skill(self, name: str) -> bool:
        """Disable a skill by name. Returns True if found."""
        skill = self._skills.get(name)
        if skill:
            skill.metadata.enabled = False
            return True
        return False
