"""Plugin architecture — unified extensibility for tools, channels, providers, memory."""

from .manager import PluginManager
from .types import LoadedPlugin, PluginManifest, PluginType

__all__ = ["PluginManager", "LoadedPlugin", "PluginManifest", "PluginType"]
