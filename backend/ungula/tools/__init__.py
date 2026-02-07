"""
Ungula Tools Module.

Provides tools that agents can use to interact with external systems.
"""

from .base import Tool, ToolParameter, ToolRegistry, ToolResult
from .cache import ToolResultCache
from .web_search import BraveSearchConfig, TavilySearchConfig, WebSearchTool

__all__ = [
    "Tool",
    "ToolParameter",
    "ToolRegistry",
    "ToolResult",
    "ToolResultCache",
    "BraveSearchConfig",
    "TavilySearchConfig",
    "WebSearchTool",
]
