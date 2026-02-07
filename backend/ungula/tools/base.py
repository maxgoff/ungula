"""
Base Tool Interface.

Defines the abstract Tool class and ToolResult for tool implementations.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Result of a tool execution."""

    success: bool
    output: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_message(self) -> str:
        """Format result for inclusion in LLM context."""
        if self.success:
            return self.output
        return f"Error: {self.error or 'Unknown error'}"


@dataclass
class ToolParameter:
    """Definition of a tool parameter."""

    name: str
    description: str
    type: str = "string"
    required: bool = True
    default: Any = None


class Tool(ABC):
    """
    Abstract base class for tools.

    Tools are callable functions that agents can use to interact
    with external systems or perform specific operations.
    """

    name: str
    description: str
    parameters: list[ToolParameter] = []
    cacheable: bool = False
    cache_ttl: int = 300

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute the tool with given parameters.

        Args:
            **kwargs: Tool-specific parameters.

        Returns:
            ToolResult with success status and output.
        """
        pass

    def get_schema(self) -> dict[str, Any]:
        """
        Get the tool schema for LLM function calling.

        Returns:
            OpenAI-compatible function schema.
        """
        properties = {}
        required = []

        for param in self.parameters:
            properties[param.name] = {
                "type": param.type,
                "description": param.description,
            }
            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


class ToolRegistry:
    """Registry for available tools."""

    def __init__(self, cache=None, event_bus=None):
        self._tools: dict[str, Tool] = {}
        self._cache = cache
        self._event_bus = event_bus

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def get_all(self) -> list[Tool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_schemas(self) -> list[dict[str, Any]]:
        """Get schemas for all registered tools."""
        return [tool.get_schema() for tool in self._tools.values()]

    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        """Execute a tool by name, with optional caching and event emission."""
        tool = self.get(name)
        if not tool:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown tool: {name}",
            )

        # Check cache for cacheable tools
        cache_key = None
        if self._cache and tool.cacheable:
            from .cache import ToolResultCache

            cache_key = ToolResultCache.make_key(name, kwargs)
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.debug("Cache hit for %s", name)
                return cached

        result = await tool.execute(**kwargs)

        # Store successful results in cache
        if cache_key and result.success:
            self._cache.put(cache_key, result, tool.cache_ttl)

        # Emit tool.executed event
        if self._event_bus and result.success:
            try:
                from ..events.types import Event

                self._event_bus.emit(Event(
                    type="tool.executed",
                    data={"tool_name": name, "args": kwargs},
                ))
            except Exception:
                pass

        return result

    def get_tool_definitions(self) -> list:
        """Get ToolDefinition objects for LLM CompletionRequest.

        Bridges the gap between Tool.get_schema() (dict format) and
        CompletionRequest.tools (list[ToolDefinition] format).
        """
        from ..llm.base import ToolDefinition

        definitions = []
        for tool in self._tools.values():
            schema = tool.get_schema()
            func = schema["function"]
            definitions.append(
                ToolDefinition(
                    name=func["name"],
                    description=func["description"],
                    parameters=func["parameters"],
                )
            )
        return definitions
