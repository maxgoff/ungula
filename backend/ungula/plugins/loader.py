"""
Plugin loader — discovers and loads plugin.yaml files.
"""

import importlib.util
import logging
from pathlib import Path
from typing import Any

import yaml

from .types import LoadedPlugin, PluginManifest, PluginType

logger = logging.getLogger(__name__)


class PluginLoader:
    """Discovers and loads plugins from directories."""

    def scan_directories(self, dirs: list[Path]) -> list[LoadedPlugin]:
        """Scan directories for plugin.yaml files."""
        plugins: dict[str, LoadedPlugin] = {}

        for directory in dirs:
            if not directory.exists():
                continue

            for child in sorted(directory.iterdir()):
                if not child.is_dir():
                    continue

                manifest_path = child / "plugin.yaml"
                if not manifest_path.exists():
                    # Also check plugin.yml
                    manifest_path = child / "plugin.yml"
                    if not manifest_path.exists():
                        continue

                plugin = self._load_plugin(child, manifest_path)
                if plugin:
                    plugins[plugin.name] = plugin

        return list(plugins.values())

    def _load_plugin(self, plugin_dir: Path, manifest_path: Path) -> LoadedPlugin | None:
        """Load a single plugin from its directory."""
        try:
            with open(manifest_path) as f:
                raw = yaml.safe_load(f) or {}

            manifest = PluginManifest(**raw)
        except Exception as e:
            logger.warning("Failed to parse plugin manifest %s: %s", manifest_path, e)
            return LoadedPlugin(
                manifest=PluginManifest(name=plugin_dir.name, type=PluginType.TOOL),
                plugin_dir=plugin_dir,
                error=f"Invalid manifest: {e}",
            )

        # Check requirements
        reqs = manifest.requires
        if reqs.get("python"):
            # Could add version check here
            pass

        # Load entry point module
        module = None
        entry_path = plugin_dir / manifest.entry_point
        if entry_path.exists():
            try:
                spec = importlib.util.spec_from_file_location(
                    f"ungula.plugins.{manifest.name}", entry_path
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
            except Exception as e:
                logger.warning("Failed to load plugin module %s: %s", entry_path, e)
                return LoadedPlugin(
                    manifest=manifest,
                    plugin_dir=plugin_dir,
                    error=f"Module load error: {e}",
                )

        return LoadedPlugin(
            manifest=manifest,
            plugin_dir=plugin_dir,
            module=module,
        )
