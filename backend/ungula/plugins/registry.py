"""
Plugin registry — delegates to existing registries (ToolRegistry, ChannelRegistry, etc.).
"""

import logging
from typing import Any

from .types import LoadedPlugin, PluginType

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Registry that delegates loaded plugins to the appropriate subsystem registry."""

    def __init__(
        self,
        tool_registry: Any = None,
        channel_registry: Any = None,
        provider_registry: Any = None,
    ):
        self.tool_registry = tool_registry
        self.channel_registry = channel_registry
        self.provider_registry = provider_registry

    def register_plugin(self, plugin: LoadedPlugin) -> bool:
        """Register a plugin with the appropriate subsystem.

        Looks for standard exports in the plugin module:
        - Tool plugins: looks for Tool subclasses
        - Channel plugins: looks for ChannelProvider subclasses
        - Provider plugins: looks for LLMProvider subclasses
        """
        if not plugin.module:
            logger.warning("Plugin %s has no module loaded", plugin.name)
            return False

        if plugin.plugin_type == PluginType.TOOL:
            return self._register_tool_plugin(plugin)
        elif plugin.plugin_type == PluginType.CHANNEL:
            return self._register_channel_plugin(plugin)
        elif plugin.plugin_type == PluginType.PROVIDER:
            return self._register_provider_plugin(plugin)
        elif plugin.plugin_type == PluginType.MEMORY:
            logger.info("Memory plugin registration not yet supported: %s", plugin.name)
            return False

        return False

    def _register_tool_plugin(self, plugin: LoadedPlugin) -> bool:
        """Register tool(s) from a plugin."""
        if not self.tool_registry:
            return False

        from ..tools.base import Tool

        registered = 0
        for attr_name in dir(plugin.module):
            attr = getattr(plugin.module, attr_name)
            if isinstance(attr, type) and issubclass(attr, Tool) and attr is not Tool:
                try:
                    tool_instance = attr()
                    self.tool_registry.register(tool_instance)
                    registered += 1
                    logger.info("Registered tool from plugin %s: %s", plugin.name, tool_instance.name)
                except Exception as e:
                    logger.warning("Failed to instantiate tool %s: %s", attr_name, e)

        return registered > 0

    def _register_channel_plugin(self, plugin: LoadedPlugin) -> bool:
        """Register a channel provider from a plugin."""
        if not self.channel_registry:
            return False

        # Look for a register() function or ChannelProvider subclass
        register_fn = getattr(plugin.module, "register", None)
        if register_fn and callable(register_fn):
            try:
                register_fn(self.channel_registry)
                logger.info("Registered channel plugin: %s", plugin.name)
                return True
            except Exception as e:
                logger.warning("Failed to register channel plugin %s: %s", plugin.name, e)

        return False

    def _register_provider_plugin(self, plugin: LoadedPlugin) -> bool:
        """Register an LLM provider from a plugin."""
        if not self.provider_registry:
            return False

        register_fn = getattr(plugin.module, "register", None)
        if register_fn and callable(register_fn):
            try:
                register_fn(self.provider_registry)
                logger.info("Registered provider plugin: %s", plugin.name)
                return True
            except Exception as e:
                logger.warning("Failed to register provider plugin %s: %s", plugin.name, e)

        return False
