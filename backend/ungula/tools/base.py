"""
Base Tool Interface.

Defines the abstract Tool class and ToolResult for tool implementations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


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

    def __init__(self):
        self._tools: dict[str, Tool] = {}

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
        """Execute a tool by name."""
        tool = self.get(name)
        if not tool:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown tool: {name}",
            )
        return await tool.execute(**kwargs)

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
