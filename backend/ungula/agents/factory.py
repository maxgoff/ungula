"""
Agent runner factory for per-agent configuration.

Creates and caches AgentRunner instances with agent-specific overrides
for provider, model, temperature, system_prompt, etc.
"""

import logging
from pathlib import Path
from typing import Any

from ..config import AgentConfig
from ..llm.registry import ProviderRegistry
from ..skills.loader import SkillRegistry
from ..storage.base import StorageBackend
from ..tools.base import ToolRegistry
from ..tools.policy import PolicyEngine
from .compaction import CompactionConfig
from .context_pruning import PruningConfig
from .runner import AgentRunner

logger = logging.getLogger(__name__)


class AgentRunnerFactory:
    """
    Factory for creating per-agent AgentRunner instances.

    Caches runners by agent ID. Falls back to the default runner
    for unknown agent IDs.
    """

    def __init__(
        self,
        storage: StorageBackend,
        registry: ProviderRegistry,
        workspace_dir: Path,
        tool_registry: ToolRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        policy_engine: PolicyEngine | None = None,
        compaction_config: CompactionConfig | None = None,
        pruning_config: PruningConfig | None = None,
        defaults: dict[str, Any] | None = None,
    ):
        self.storage = storage
        self.registry = registry
        self.workspace_dir = workspace_dir
        self.tool_registry = tool_registry
        self.skill_registry = skill_registry
        self.policy_engine = policy_engine
        self.compaction_config = compaction_config
        self.pruning_config = pruning_config
        self.defaults = defaults or {}
        self._cache: dict[str, AgentRunner] = {}

    def get_or_create(
        self,
        agent_id: str,
        agent_configs: list[AgentConfig],
    ) -> AgentRunner:
        """
        Get or create an AgentRunner for the given agent ID.

        If the agent_id matches a config in agent_configs, returns a
        runner with that agent's specific overrides. Otherwise returns
        a default runner.
        """
        if agent_id in self._cache:
            return self._cache[agent_id]

        # Find agent config
        agent_config = None
        for cfg in agent_configs:
            if cfg.id == agent_id and cfg.enabled:
                agent_config = cfg
                break

        if agent_config is None:
            logger.warning("Agent '%s' not found or disabled, using defaults", agent_id)
            return self._create_default_runner()

        runner = AgentRunner(
            storage=self.storage,
            registry=self.registry,
            workspace_dir=self.workspace_dir,
            default_provider=agent_config.provider or self.defaults.get("default_provider"),
            default_model=agent_config.model or self.defaults.get("default_model"),
            default_temperature=agent_config.temperature or self.defaults.get("default_temperature", 0.7),
            default_max_tokens=agent_config.max_tokens or self.defaults.get("default_max_tokens"),
            max_tool_iterations=agent_config.max_tool_iterations or self.defaults.get("max_tool_iterations", 10),
            tool_registry=self.tool_registry,
            skill_registry=self.skill_registry,
            policy_engine=self.policy_engine,
            compaction_config=self.compaction_config,
            pruning_config=self.pruning_config,
        )

        self._cache[agent_id] = runner
        logger.info(
            "Created runner for agent '%s' (provider=%s, model=%s)",
            agent_id, agent_config.provider, agent_config.model,
        )
        return runner

    def _create_default_runner(self) -> AgentRunner:
        """Create a runner with default settings."""
        return AgentRunner(
            storage=self.storage,
            registry=self.registry,
            workspace_dir=self.workspace_dir,
            default_provider=self.defaults.get("default_provider"),
            default_model=self.defaults.get("default_model"),
            tool_registry=self.tool_registry,
            skill_registry=self.skill_registry,
            policy_engine=self.policy_engine,
            compaction_config=self.compaction_config,
            pruning_config=self.pruning_config,
        )

    def invalidate(self, agent_id: str | None = None) -> None:
        """Clear cached runners. If agent_id is None, clears all."""
        if agent_id:
            self._cache.pop(agent_id, None)
            logger.info("Invalidated runner cache for agent '%s'", agent_id)
        else:
            self._cache.clear()
            logger.info("Invalidated all runner caches")

    def update_registry(self, registry: ProviderRegistry) -> None:
        """Update the registry reference for all cached runners."""
        self.registry = registry
        for runner in self._cache.values():
            runner.registry = registry
