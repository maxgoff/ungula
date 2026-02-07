"""
Plugin manager — orchestrates discovery, loading, enabling/disabling, and installation.
"""

import logging
from pathlib import Path
from typing import Any

from .installer import PluginInstaller
from .loader import PluginLoader
from .registry import PluginRegistry
from .types import LoadedPlugin

logger = logging.getLogger(__name__)


class PluginManager:
    """Manages the full plugin lifecycle."""

    def __init__(
        self,
        plugin_dirs: list[Path],
        plugin_registry: PluginRegistry,
    ):
        self._plugins: dict[str, LoadedPlugin] = {}
        self.loader = PluginLoader()
        self.registry = plugin_registry
        self.plugin_dirs = plugin_dirs
        # Use the first user-writable dir for installations
        self.installer = PluginInstaller(plugin_dirs[0] if plugin_dirs else Path.home() / ".ungula" / "plugins")

    async def discover(self) -> list[LoadedPlugin]:
        """Discover and load all plugins from configured directories."""
        plugins = self.loader.scan_directories(self.plugin_dirs)
        for plugin in plugins:
            self._plugins[plugin.name] = plugin
        logger.info("Discovered %d plugins", len(plugins))
        return plugins

    def list_plugins(self) -> list[dict[str, Any]]:
        """List all discovered plugins."""
        return [p.to_dict() for p in self._plugins.values()]

    def get_plugin(self, name: str) -> LoadedPlugin | None:
        return self._plugins.get(name)

    def enable(self, name: str) -> bool:
        """Enable a plugin and register it with the appropriate subsystem."""
        plugin = self._plugins.get(name)
        if not plugin:
            return False
        if plugin.error:
            logger.warning("Cannot enable plugin %s: %s", name, plugin.error)
            return False

        plugin.enabled = True
        self.registry.register_plugin(plugin)
        logger.info("Enabled plugin: %s", name)
        return True

    def disable(self, name: str) -> bool:
        """Disable a plugin."""
        plugin = self._plugins.get(name)
        if not plugin:
            return False

        plugin.enabled = False
        # Note: we don't unregister tools/channels dynamically (would need restart)
        logger.info("Disabled plugin: %s", name)
        return True

    def install(self, source_path: str) -> dict[str, Any]:
        """Install a plugin from a local path."""
        result = self.installer.install_from_path(Path(source_path))
        if result.get("success"):
            # Re-scan to pick up the new plugin
            plugins = self.loader.scan_directories(self.plugin_dirs)
            for p in plugins:
                self._plugins[p.name] = p
        return result

    def uninstall(self, name: str) -> bool:
        """Uninstall a plugin."""
        self._plugins.pop(name, None)
        return self.installer.uninstall(name)

    async def reload(self) -> list[LoadedPlugin]:
        """Reload all plugins from disk."""
        self._plugins.clear()
        return await self.discover()
