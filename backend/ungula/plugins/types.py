"""
Plugin type definitions.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PluginType(str, Enum):
    """Types of plugins."""

    CHANNEL = "channel"
    TOOL = "tool"
    PROVIDER = "provider"
    MEMORY = "memory"


class PluginManifest(BaseModel):
    """Parsed plugin.yaml manifest."""

    name: str = Field(description="Plugin name")
    version: str = Field(default="0.0.0", description="Plugin version")
    type: PluginType = Field(description="Plugin type")
    description: str = Field(default="", description="Plugin description")
    entry_point: str = Field(default="main.py", description="Entry point module")
    config_schema: dict[str, Any] = Field(default_factory=dict, description="JSON Schema for config")
    requires: dict[str, Any] = Field(default_factory=dict, description="Requirements")


@dataclass
class LoadedPlugin:
    """A loaded plugin with its manifest, module, and state."""

    manifest: PluginManifest
    plugin_dir: Path
    module: Any = None
    enabled: bool = False
    config: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def plugin_type(self) -> PluginType:
        return self.manifest.type

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.manifest.name,
            "version": self.manifest.version,
            "type": self.manifest.type.value,
            "description": self.manifest.description,
            "enabled": self.enabled,
            "path": str(self.plugin_dir),
            "error": self.error,
        }
