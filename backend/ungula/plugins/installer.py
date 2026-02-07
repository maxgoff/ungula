"""
Plugin installer — install plugins from local path or registry.
"""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from .types import PluginManifest

logger = logging.getLogger(__name__)


class PluginInstaller:
    """Installs plugins from various sources."""

    def __init__(self, plugin_dir: Path):
        self.plugin_dir = plugin_dir
        self.plugin_dir.mkdir(parents=True, exist_ok=True)

    def install_from_path(self, source: Path) -> dict[str, Any]:
        """Install a plugin from a local directory."""
        manifest_path = source / "plugin.yaml"
        if not manifest_path.exists():
            manifest_path = source / "plugin.yml"
        if not manifest_path.exists():
            return {"success": False, "error": "No plugin.yaml found"}

        try:
            with open(manifest_path) as f:
                raw = yaml.safe_load(f) or {}
            manifest = PluginManifest(**raw)
        except Exception as e:
            return {"success": False, "error": f"Invalid manifest: {e}"}

        # Copy to plugin directory
        target = self.plugin_dir / manifest.name
        if target.exists():
            shutil.rmtree(target)

        shutil.copytree(source, target)

        # Install Python dependencies if specified
        packages = manifest.requires.get("packages", [])
        if packages:
            try:
                subprocess.run(
                    ["pip", "install", *packages],
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
            except subprocess.CalledProcessError as e:
                logger.warning("Failed to install deps for %s: %s", manifest.name, e.stderr)

        return {
            "success": True,
            "name": manifest.name,
            "version": manifest.version,
            "type": manifest.type.value,
            "path": str(target),
        }

    def uninstall(self, name: str) -> bool:
        """Remove a plugin directory."""
        target = self.plugin_dir / name
        if target.exists():
            shutil.rmtree(target)
            return True
        return False
