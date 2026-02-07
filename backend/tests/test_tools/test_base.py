"""
Tests for the tool base classes.

Covers ToolResult, ToolParameter, Tool (abstract), ToolRegistry,
including schema generation, execution routing, and ToolDefinition bridging.
"""

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from ungula.tools.base import Tool, ToolParameter, ToolRegistry, ToolResult


# ---------------------------------------------------------------------------
# Module-level setup: mock missing third-party LLM provider dependencies
# so that ``from ungula.llm.base import ToolDefinition`` works even when
# the heavy provider SDKs (anthropic, openai, google-genai) are not installed.
# ---------------------------------------------------------------------------

_MOCK_MODULES = ["anthropic", "openai", "httpx"]
_MOCK_GOOGLE_SUBS = ["google.generativeai", "google.genai", "google.genai.types"]
_originals: dict[str, types.ModuleType | None] = {}


def _install_mocks() -> None:
    for mod in _MOCK_MODULES:
        _originals[mod] = sys.modules.get(mod)
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()

    if "google" not in sys.modules:
        google_mock = types.ModuleType("google")
        google_mock.__path__ = []  # type: ignore[attr-defined]
        _originals["google"] = None
        sys.modules["google"] = google_mock
    else:
        _originals["google"] = sys.modules["google"]

    for sub in _MOCK_GOOGLE_SUBS:
        _originals[sub] = sys.modules.get(sub)
        if sub not in sys.modules:
            sys.modules[sub] = MagicMock()


def _remove_mocks() -> None:
    for mod, orig in _originals.items():
        if orig is None:
            sys.modules.pop(mod, None)
        else:
            sys.modules[mod] = orig


_install_mocks()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class EchoTool(Tool):
    """Concrete Tool that echoes back its kwargs."""

    name = "echo"
    description = "Echoes the input back"
    parameters = [
        ToolParameter(
            name="text",
            description="Text to echo",
            type="string",
            required=True,
        ),
    ]

    async def execute(self, **kwargs: Any) -> ToolResult:
        text = kwargs.get("text", "")
        return ToolResult(success=True, output=text)


class FailTool(Tool):
    """Concrete Tool that always fails."""

    name = "fail"
    description = "Always fails"
    parameters = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=False, output="", error="Intentional failure")


class MultiParamTool(Tool):
    """Concrete Tool with multiple parameters (required and optional)."""

    name = "multi"
    description = "Tool with multiple params"
    parameters = [
        ToolParameter(
            name="query",
            description="Search query",
            type="string",
            required=True,
        ),
        ToolParameter(
            name="limit",
            description="Maximum results",
            type="integer",
            required=False,
            default=10,
        ),
        ToolParameter(
            name="verbose",
            description="Enable verbose output",
            type="boolean",
            required=False,
            default=False,
        ),
    ]

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            success=True,
            output=f"query={kwargs.get('query')} limit={kwargs.get('limit', 10)}",
            data={"kwargs": kwargs},
        )


class NoParamTool(Tool):
    """Tool with no parameters."""

    name = "noop"
    description = "Does nothing"
    parameters = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, output="done")


# ===========================================================================
# ToolResult
# ===========================================================================


class TestToolResult:
    """Tests for ToolResult construction and serialization."""

    def test_success_result_defaults(self):
        result = ToolResult(success=True, output="hello")
        assert result.success is True
        assert result.output == "hello"
        assert result.data == {}
        assert result.error is None

    def test_error_result_with_message(self):
        result = ToolResult(success=False, output="", error="Something broke")
        assert result.success is False
        assert result.output == ""
        assert result.error == "Something broke"

    def test_to_message_success(self):
        result = ToolResult(success=True, output="All good")
        assert result.to_message() == "All good"

    def test_to_message_error_with_message(self):
        result = ToolResult(success=False, output="", error="Disk full")
        assert result.to_message() == "Error: Disk full"

    def test_to_message_error_without_message(self):
        result = ToolResult(success=False, output="")
        assert result.to_message() == "Error: Unknown error"

    def test_to_message_error_none_explicit(self):
        result = ToolResult(success=False, output="", error=None)
        assert result.to_message() == "Error: Unknown error"

    def test_result_with_data(self):
        result = ToolResult(
            success=True,
            output="ok",
            data={"count": 5, "items": ["a", "b"]},
        )
        assert result.data["count"] == 5
        assert len(result.data["items"]) == 2

    def test_result_data_default_is_independent(self):
        """Each ToolResult should get its own default dict, not a shared one."""
        r1 = ToolResult(success=True, output="a")
        r2 = ToolResult(success=True, output="b")
        r1.data["key"] = "value"
        assert "key" not in r2.data

    def test_success_result_with_empty_output(self):
        result = ToolResult(success=True, output="")
        assert result.to_message() == ""

    def test_error_result_with_nonempty_output(self):
        """Even if output is populated, to_message returns error when not success."""
        result = ToolResult(success=False, output="partial data", error="Timeout")
        assert result.to_message() == "Error: Timeout"

    def test_result_fields_are_accessible(self):
        result = ToolResult(
            success=True,
            output="test",
            data={"key": "val"},
            error=None,
        )
        assert result.success is True
        assert result.output == "test"
        assert result.data == {"key": "val"}
        assert result.error is None


# ===========================================================================
# ToolParameter
# ===========================================================================


class TestToolParameter:
    """Tests for ToolParameter construction and defaults."""

    def test_required_parameter(self):
        param = ToolParameter(name="query", description="Search text")
        assert param.name == "query"
        assert param.description == "Search text"
        assert param.type == "string"
        assert param.required is True
        assert param.default is None

    def test_optional_parameter_with_default(self):
        param = ToolParameter(
            name="limit",
            description="Max results",
            type="integer",
            required=False,
            default=10,
        )
        assert param.name == "limit"
        assert param.type == "integer"
        assert param.required is False
        assert param.default == 10

    def test_boolean_parameter(self):
        param = ToolParameter(
            name="verbose",
            description="Verbose mode",
            type="boolean",
            required=False,
            default=False,
        )
        assert param.type == "boolean"
        assert param.default is False

    def test_parameter_with_custom_type(self):
        param = ToolParameter(
            name="data",
            description="Arbitrary data",
            type="object",
        )
        assert param.type == "object"

    def test_parameter_equality_by_fields(self):
        p1 = ToolParameter(name="x", description="desc", type="string", required=True, default=None)
        p2 = ToolParameter(name="x", description="desc", type="string", required=True, default=None)
        assert p1 == p2

    def test_parameter_default_none_for_required(self):
        param = ToolParameter(name="cmd", description="Command to run")
        assert param.default is None
        assert param.required is True


# ===========================================================================
# Tool (abstract class)
# ===========================================================================


class TestToolSchema:
    """Tests for Tool.get_schema() with various parameter configurations."""

    def test_schema_no_parameters(self):
        tool = NoParamTool()
        schema = tool.get_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "noop"
        assert schema["function"]["description"] == "Does nothing"
        assert schema["function"]["parameters"]["type"] == "object"
        assert schema["function"]["parameters"]["properties"] == {}
        assert schema["function"]["parameters"]["required"] == []

    def test_schema_single_required_parameter(self):
        tool = EchoTool()
        schema = tool.get_schema()
        func = schema["function"]
        assert func["name"] == "echo"
        assert "text" in func["parameters"]["properties"]
        assert func["parameters"]["properties"]["text"]["type"] == "string"
        assert func["parameters"]["properties"]["text"]["description"] == "Text to echo"
        assert func["parameters"]["required"] == ["text"]

    def test_schema_multiple_parameters_required_and_optional(self):
        tool = MultiParamTool()
        schema = tool.get_schema()
        func = schema["function"]
        props = func["parameters"]["properties"]
        required = func["parameters"]["required"]

        assert len(props) == 3
        assert "query" in props
        assert "limit" in props
        assert "verbose" in props

        assert props["query"]["type"] == "string"
        assert props["limit"]["type"] == "integer"
        assert props["verbose"]["type"] == "boolean"

        # Only 'query' is required
        assert required == ["query"]

    def test_schema_is_openai_compatible(self):
        """Schema should have the structure expected by OpenAI function calling."""
        tool = EchoTool()
        schema = tool.get_schema()
        assert "type" in schema
        assert schema["type"] == "function"
        assert "function" in schema
        assert "name" in schema["function"]
        assert "description" in schema["function"]
        assert "parameters" in schema["function"]
        assert "type" in schema["function"]["parameters"]
        assert "properties" in schema["function"]["parameters"]
        assert "required" in schema["function"]["parameters"]

    def test_tool_cannot_be_instantiated_directly(self):
        """Tool is abstract; direct instantiation should fail."""
        with pytest.raises(TypeError):
            Tool()  # type: ignore[abstract]

    def test_schema_preserves_parameter_descriptions(self):
        tool = MultiParamTool()
        schema = tool.get_schema()
        props = schema["function"]["parameters"]["properties"]
        assert props["query"]["description"] == "Search query"
        assert props["limit"]["description"] == "Maximum results"
        assert props["verbose"]["description"] == "Enable verbose output"


# ===========================================================================
# ToolRegistry
# ===========================================================================


class TestToolRegistry:
    """Tests for ToolRegistry registration, lookup, and execution."""

    def test_register_and_get(self):
        registry = ToolRegistry()
        tool = EchoTool()
        registry.register(tool)
        assert registry.get("echo") is tool

    def test_get_unknown_returns_none(self):
        registry = ToolRegistry()
        assert registry.get("nonexistent") is None

    def test_list_tools_empty(self):
        registry = ToolRegistry()
        assert registry.list_tools() == []

    def test_list_tools_after_registration(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        registry.register(FailTool())
        names = registry.list_tools()
        assert "echo" in names
        assert "fail" in names
        assert len(names) == 2

    def test_get_all_empty(self):
        registry = ToolRegistry()
        assert registry.get_all() == []

    def test_get_all_returns_all_tools(self):
        registry = ToolRegistry()
        echo = EchoTool()
        fail = FailTool()
        registry.register(echo)
        registry.register(fail)
        all_tools = registry.get_all()
        assert len(all_tools) == 2
        assert echo in all_tools
        assert fail in all_tools

    def test_get_schemas_empty(self):
        registry = ToolRegistry()
        assert registry.get_schemas() == []

    def test_get_schemas_returns_schemas_for_all(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        registry.register(MultiParamTool())
        schemas = registry.get_schemas()
        assert len(schemas) == 2
        names = [s["function"]["name"] for s in schemas]
        assert "echo" in names
        assert "multi" in names

    @pytest.mark.asyncio
    async def test_execute_known_tool(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        result = await registry.execute("echo", text="hello world")
        assert result.success is True
        assert result.output == "hello world"

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        registry = ToolRegistry()
        result = await registry.execute("nonexistent", foo="bar")
        assert result.success is False
        assert result.error == "Unknown tool: nonexistent"
        assert result.output == ""

    @pytest.mark.asyncio
    async def test_execute_failing_tool(self):
        registry = ToolRegistry()
        registry.register(FailTool())
        result = await registry.execute("fail")
        assert result.success is False
        assert result.error == "Intentional failure"

    def test_register_overwrites_same_name(self):
        """Registering a tool with the same name replaces the previous one."""
        registry = ToolRegistry()
        tool1 = EchoTool()
        tool2 = EchoTool()
        registry.register(tool1)
        registry.register(tool2)
        assert registry.get("echo") is tool2
        assert len(registry.list_tools()) == 1

    def test_register_multiple_distinct_tools(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        registry.register(FailTool())
        registry.register(MultiParamTool())
        registry.register(NoParamTool())
        assert len(registry.list_tools()) == 4

    @pytest.mark.asyncio
    async def test_execute_with_multiple_kwargs(self):
        registry = ToolRegistry()
        registry.register(MultiParamTool())
        result = await registry.execute("multi", query="test", limit=5)
        assert result.success is True
        assert "query=test" in result.output
        assert "limit=5" in result.output


# ===========================================================================
# ToolRegistry.get_tool_definitions
# ===========================================================================


class TestToolRegistryDefinitions:
    """Tests for ToolRegistry.get_tool_definitions() bridging to ToolDefinition.

    These tests require ``ungula.llm.base.ToolDefinition`` which transitively
    pulls in LLM provider SDKs.  Module-level mocks (installed above) ensure
    the import succeeds even without those SDKs installed.
    """

    def _get_tool_definition_cls(self):
        """Import ToolDefinition (safe because mocks are in place)."""
        from ungula.llm.base import ToolDefinition
        return ToolDefinition

    def test_get_tool_definitions_empty(self):
        registry = ToolRegistry()
        defs = registry.get_tool_definitions()
        assert defs == []

    def test_get_tool_definitions_returns_tool_definition_objects(self):
        ToolDefinition = self._get_tool_definition_cls()
        registry = ToolRegistry()
        registry.register(EchoTool())
        defs = registry.get_tool_definitions()
        assert len(defs) == 1
        assert isinstance(defs[0], ToolDefinition)

    def test_get_tool_definitions_has_correct_fields(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        defs = registry.get_tool_definitions()
        defn = defs[0]
        assert defn.name == "echo"
        assert defn.description == "Echoes the input back"
        assert "properties" in defn.parameters
        assert "text" in defn.parameters["properties"]

    def test_get_tool_definitions_multiple_tools(self):
        ToolDefinition = self._get_tool_definition_cls()
        registry = ToolRegistry()
        registry.register(EchoTool())
        registry.register(MultiParamTool())
        registry.register(NoParamTool())
        defs = registry.get_tool_definitions()
        assert len(defs) == 3
        names = {d.name for d in defs}
        assert names == {"echo", "multi", "noop"}
        for d in defs:
            assert isinstance(d, ToolDefinition)

    def test_get_tool_definitions_parameters_match_schema(self):
        """ToolDefinition.parameters should match the 'parameters' key from get_schema."""
        registry = ToolRegistry()
        tool = MultiParamTool()
        registry.register(tool)

        schema = tool.get_schema()
        expected_params = schema["function"]["parameters"]

        defs = registry.get_tool_definitions()
        assert defs[0].parameters == expected_params

    def test_get_tool_definitions_required_list_accurate(self):
        registry = ToolRegistry()
        registry.register(MultiParamTool())
        defs = registry.get_tool_definitions()
        params = defs[0].parameters
        assert params["required"] == ["query"]
