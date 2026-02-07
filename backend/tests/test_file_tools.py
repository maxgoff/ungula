"""
Tests for file operation tools: read, write, edit, search.

Covers path traversal prevention, extension blocking, file size limits,
line ranges, find-and-replace semantics, and case-insensitive search.
"""

import os
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock missing third-party LLM provider SDKs before importing tools.
# ---------------------------------------------------------------------------

_MOCK_MODULES = ["anthropic", "openai", "httpx"]
_MOCK_GOOGLE_SUBS = ["google.generativeai", "google.genai", "google.genai.types"]

for _mod in _MOCK_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

if "google" not in sys.modules:
    _google_mock = types.ModuleType("google")
    _google_mock.__path__ = []  # type: ignore[attr-defined]
    sys.modules["google"] = _google_mock

for _sub in _MOCK_GOOGLE_SUBS:
    if _sub not in sys.modules:
        sys.modules[_sub] = MagicMock()

from ungula.config import FileToolsConfig
from ungula.skills.builtin.file_ops.tools import (
    FileEditTool,
    FileReadTool,
    FileSearchTool,
    FileWriteTool,
    _check_extension,
    _resolve_safe_path,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a workspace directory with some test files."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    # Create test files
    (ws / "hello.txt").write_text("Hello, world!\nLine two\nLine three\n")
    (ws / "data.py").write_text("import os\n\ndef greet():\n    print('hello')\n")
    (ws / "sub").mkdir()
    (ws / "sub" / "nested.md").write_text("# Title\nSome content here\n")

    return ws


@pytest.fixture
def config() -> FileToolsConfig:
    return FileToolsConfig()


@pytest.fixture
def strict_config() -> FileToolsConfig:
    return FileToolsConfig(denied_extensions=[".env", ".key", ".pem", ".secret"])


@pytest.fixture
def read_tool(workspace: Path, config: FileToolsConfig) -> FileReadTool:
    return FileReadTool(workspace, config)


@pytest.fixture
def write_tool(workspace: Path, config: FileToolsConfig) -> FileWriteTool:
    return FileWriteTool(workspace, config)


@pytest.fixture
def edit_tool(workspace: Path, config: FileToolsConfig) -> FileEditTool:
    return FileEditTool(workspace, config)


@pytest.fixture
def search_tool(workspace: Path, config: FileToolsConfig) -> FileSearchTool:
    return FileSearchTool(workspace, config)


# ===========================================================================
# _resolve_safe_path
# ===========================================================================


class TestResolveSafePath:
    """Tests for path traversal prevention."""

    def test_normal_relative_path(self, workspace: Path):
        result = _resolve_safe_path(workspace, "hello.txt")
        assert result is not None
        assert result == (workspace / "hello.txt").resolve()

    def test_nested_relative_path(self, workspace: Path):
        result = _resolve_safe_path(workspace, "sub/nested.md")
        assert result is not None
        assert result.name == "nested.md"

    def test_dotdot_escapes_workspace(self, workspace: Path):
        result = _resolve_safe_path(workspace, "../../../etc/passwd")
        assert result is None

    def test_dotdot_within_workspace(self, workspace: Path):
        result = _resolve_safe_path(workspace, "sub/../hello.txt")
        assert result is not None
        assert result == (workspace / "hello.txt").resolve()

    def test_absolute_path_outside(self, workspace: Path):
        result = _resolve_safe_path(workspace, "/etc/passwd")
        assert result is None

    def test_double_dot_with_trailing(self, workspace: Path):
        result = _resolve_safe_path(workspace, "sub/../../outside")
        assert result is None

    def test_symlink_outside_workspace(self, workspace: Path):
        """Symlink pointing outside workspace should be rejected."""
        link = workspace / "evil_link"
        try:
            link.symlink_to("/etc/passwd")
        except OSError:
            pytest.skip("Cannot create symlinks on this system")
        result = _resolve_safe_path(workspace, "evil_link")
        # The resolve() follows the symlink, and /etc/passwd is not under workspace
        assert result is None

    def test_empty_path(self, workspace: Path):
        """Empty path resolves to workspace root itself."""
        result = _resolve_safe_path(workspace, "")
        # "" joined with workspace gives workspace itself
        assert result == workspace.resolve()


# ===========================================================================
# _check_extension
# ===========================================================================


class TestCheckExtension:
    """Tests for denied extension checking."""

    def test_denied_env(self):
        assert _check_extension(Path("config.env"), [".env"]) is not None

    def test_denied_key(self):
        assert _check_extension(Path("server.key"), [".key"]) is not None

    def test_allowed_py(self):
        assert _check_extension(Path("main.py"), [".env", ".key"]) is None

    def test_allowed_txt(self):
        assert _check_extension(Path("notes.txt"), [".env"]) is None

    def test_empty_denied_list(self):
        assert _check_extension(Path("any.env"), []) is None

    def test_double_extension(self):
        result = _check_extension(Path("backup.tar.env"), [".env"])
        assert result is not None


# ===========================================================================
# FileReadTool
# ===========================================================================


class TestFileReadTool:
    """Tests for FileReadTool.execute."""

    @pytest.mark.asyncio
    async def test_read_existing_file(self, read_tool: FileReadTool):
        result = await read_tool.execute(path="hello.txt")
        assert result.success is True
        assert "Hello, world!" in result.output

    @pytest.mark.asyncio
    async def test_read_with_line_numbers(self, read_tool: FileReadTool):
        result = await read_tool.execute(path="hello.txt")
        assert result.success is True
        # Line numbers should be present
        assert "1\t" in result.output

    @pytest.mark.asyncio
    async def test_read_with_offset_and_limit(self, read_tool: FileReadTool):
        result = await read_tool.execute(path="hello.txt", offset=2, limit=1)
        assert result.success is True
        assert "Line two" in result.output
        assert "Hello, world!" not in result.output

    @pytest.mark.asyncio
    async def test_read_nested_file(self, read_tool: FileReadTool):
        result = await read_tool.execute(path="sub/nested.md")
        assert result.success is True
        assert "Title" in result.output

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, read_tool: FileReadTool):
        result = await read_tool.execute(path="missing.txt")
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_directory(self, read_tool: FileReadTool):
        result = await read_tool.execute(path="sub")
        assert result.success is False
        assert "not a file" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_empty_path(self, read_tool: FileReadTool):
        result = await read_tool.execute(path="")
        assert result.success is False
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_path_traversal_blocked(self, read_tool: FileReadTool):
        result = await read_tool.execute(path="../../../etc/passwd")
        assert result.success is False
        assert "outside workspace" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_denied_extension(self, workspace: Path, strict_config: FileToolsConfig):
        (workspace / "secrets.env").write_text("API_KEY=123")
        tool = FileReadTool(workspace, strict_config)
        result = await tool.execute(path="secrets.env")
        assert result.success is False
        assert "blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_large_file_blocked(self, workspace: Path):
        config = FileToolsConfig(max_file_size=10)
        (workspace / "big.txt").write_text("x" * 100)
        tool = FileReadTool(workspace, config)
        result = await tool.execute(path="big.txt")
        assert result.success is False
        assert "too large" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_returns_path_and_size(self, read_tool: FileReadTool):
        result = await read_tool.execute(path="hello.txt")
        assert result.success is True
        assert "path" in result.data
        assert "size" in result.data


# ===========================================================================
# FileWriteTool
# ===========================================================================


class TestFileWriteTool:
    """Tests for FileWriteTool.execute."""

    @pytest.mark.asyncio
    async def test_write_new_file(self, write_tool: FileWriteTool, workspace: Path):
        result = await write_tool.execute(path="new_file.txt", content="New content")
        assert result.success is True
        assert (workspace / "new_file.txt").read_text() == "New content"

    @pytest.mark.asyncio
    async def test_write_overwrite(self, write_tool: FileWriteTool, workspace: Path):
        result = await write_tool.execute(path="hello.txt", content="Overwritten")
        assert result.success is True
        assert (workspace / "hello.txt").read_text() == "Overwritten"

    @pytest.mark.asyncio
    async def test_append_mode(self, write_tool: FileWriteTool, workspace: Path):
        original = (workspace / "hello.txt").read_text()
        result = await write_tool.execute(path="hello.txt", content="\nAppended", mode="append")
        assert result.success is True
        assert (workspace / "hello.txt").read_text() == original + "\nAppended"

    @pytest.mark.asyncio
    async def test_write_creates_parent_dirs(self, write_tool: FileWriteTool, workspace: Path):
        result = await write_tool.execute(path="deep/nested/dir/file.txt", content="Deep")
        assert result.success is True
        assert (workspace / "deep" / "nested" / "dir" / "file.txt").read_text() == "Deep"

    @pytest.mark.asyncio
    async def test_write_empty_path(self, write_tool: FileWriteTool):
        result = await write_tool.execute(path="", content="test")
        assert result.success is False
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_write_path_traversal_blocked(self, write_tool: FileWriteTool):
        result = await write_tool.execute(path="../../evil.txt", content="hack")
        assert result.success is False
        assert "outside workspace" in result.error.lower()

    @pytest.mark.asyncio
    async def test_write_denied_extension(self, workspace: Path, strict_config: FileToolsConfig):
        tool = FileWriteTool(workspace, strict_config)
        result = await tool.execute(path="secrets.env", content="API_KEY=hack")
        assert result.success is False
        assert "blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_write_content_too_large(self, workspace: Path):
        config = FileToolsConfig(max_file_size=10)
        tool = FileWriteTool(workspace, config)
        result = await tool.execute(path="big.txt", content="x" * 100)
        assert result.success is False
        assert "max file size" in result.error.lower()

    @pytest.mark.asyncio
    async def test_write_returns_path_and_bytes(self, write_tool: FileWriteTool):
        result = await write_tool.execute(path="test.txt", content="hello")
        assert result.success is True
        assert "path" in result.data
        assert "bytes" in result.data
        assert result.data["bytes"] == 5


# ===========================================================================
# FileEditTool
# ===========================================================================


class TestFileEditTool:
    """Tests for FileEditTool.execute (find-and-replace)."""

    @pytest.mark.asyncio
    async def test_single_replacement(self, edit_tool: FileEditTool, workspace: Path):
        result = await edit_tool.execute(path="hello.txt", old_text="Hello, world!", new_text="Goodbye, world!")
        assert result.success is True
        content = (workspace / "hello.txt").read_text()
        assert "Goodbye, world!" in content
        assert "Hello, world!" not in content

    @pytest.mark.asyncio
    async def test_old_text_not_found(self, edit_tool: FileEditTool):
        result = await edit_tool.execute(path="hello.txt", old_text="NONEXISTENT", new_text="replacement")
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_ambiguous_match_rejected(self, workspace: Path, config: FileToolsConfig):
        """Multiple matches without replace_all should fail."""
        (workspace / "dup.txt").write_text("foo bar foo baz foo")
        tool = FileEditTool(workspace, config)
        result = await tool.execute(path="dup.txt", old_text="foo", new_text="qux")
        assert result.success is False
        assert "3 times" in result.error

    @pytest.mark.asyncio
    async def test_replace_all(self, workspace: Path, config: FileToolsConfig):
        (workspace / "dup.txt").write_text("foo bar foo baz foo")
        tool = FileEditTool(workspace, config)
        result = await tool.execute(path="dup.txt", old_text="foo", new_text="qux", replace_all=True)
        assert result.success is True
        assert (workspace / "dup.txt").read_text() == "qux bar qux baz qux"
        assert result.data["replacements"] == 3

    @pytest.mark.asyncio
    async def test_edit_nonexistent_file(self, edit_tool: FileEditTool):
        result = await edit_tool.execute(path="missing.txt", old_text="x", new_text="y")
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_edit_path_traversal(self, edit_tool: FileEditTool):
        result = await edit_tool.execute(path="../../etc/passwd", old_text="root", new_text="hack")
        assert result.success is False
        assert "outside workspace" in result.error.lower()

    @pytest.mark.asyncio
    async def test_edit_denied_extension(self, workspace: Path, strict_config: FileToolsConfig):
        (workspace / "creds.key").write_text("private key data")
        tool = FileEditTool(workspace, strict_config)
        result = await tool.execute(path="creds.key", old_text="private", new_text="hacked")
        assert result.success is False
        assert "blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_edit_empty_old_text(self, edit_tool: FileEditTool):
        result = await edit_tool.execute(path="hello.txt", old_text="", new_text="x")
        assert result.success is False
        assert "required" in result.error.lower()


# ===========================================================================
# FileSearchTool
# ===========================================================================


class TestFileSearchTool:
    """Tests for FileSearchTool.execute."""

    @pytest.mark.asyncio
    async def test_search_finds_match(self, search_tool: FileSearchTool):
        result = await search_tool.execute(query="Hello")
        assert result.success is True
        assert result.data["count"] > 0
        assert "hello.txt" in result.output

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self, search_tool: FileSearchTool):
        result = await search_tool.execute(query="hello")
        assert result.success is True
        assert result.data["count"] > 0

    @pytest.mark.asyncio
    async def test_search_no_matches(self, search_tool: FileSearchTool):
        result = await search_tool.execute(query="ZZZZNOTHERE")
        assert result.success is True
        assert result.data["count"] == 0
        assert "No matches" in result.output

    @pytest.mark.asyncio
    async def test_search_with_glob(self, search_tool: FileSearchTool):
        result = await search_tool.execute(query="import", glob="*.py")
        assert result.success is True
        assert result.data["count"] > 0
        assert "data.py" in result.output

    @pytest.mark.asyncio
    async def test_search_max_results(self, workspace: Path, config: FileToolsConfig):
        # Create a file with many matching lines
        (workspace / "many.txt").write_text("\n".join(f"match {i}" for i in range(50)))
        tool = FileSearchTool(workspace, config)
        result = await tool.execute(query="match", max_results=5)
        assert result.success is True
        assert result.data["count"] == 5

    @pytest.mark.asyncio
    async def test_search_empty_query(self, search_tool: FileSearchTool):
        result = await search_tool.execute(query="")
        assert result.success is False
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_search_includes_line_numbers(self, search_tool: FileSearchTool):
        result = await search_tool.execute(query="Line two")
        assert result.success is True
        # Output format: path:line:content
        assert ":2:" in result.output

    @pytest.mark.asyncio
    async def test_search_skips_denied_extensions(self, workspace: Path, strict_config: FileToolsConfig):
        (workspace / "secrets.env").write_text("API_KEY=findme")
        tool = FileSearchTool(workspace, strict_config)
        result = await tool.execute(query="findme")
        assert result.success is True
        assert result.data["count"] == 0

    @pytest.mark.asyncio
    async def test_search_returns_output_format(self, search_tool: FileSearchTool):
        result = await search_tool.execute(query="Title")
        assert result.success is True
        # Format: relpath:lineno:content
        lines = result.output.strip().split("\n")
        assert len(lines) >= 1
        parts = lines[0].split(":")
        assert len(parts) >= 3


# ===========================================================================
# Tool metadata
# ===========================================================================


class TestFileToolMetadata:
    """Tests for tool name, description, and schema."""

    def test_read_tool_name(self, read_tool: FileReadTool):
        assert read_tool.name == "file_read"

    def test_write_tool_name(self, write_tool: FileWriteTool):
        assert write_tool.name == "file_write"

    def test_edit_tool_name(self, edit_tool: FileEditTool):
        assert edit_tool.name == "file_edit"

    def test_search_tool_name(self, search_tool: FileSearchTool):
        assert search_tool.name == "file_search"

    def test_read_schema(self, read_tool: FileReadTool):
        schema = read_tool.get_schema()
        assert schema["type"] == "function"
        assert "path" in schema["function"]["parameters"]["properties"]

    def test_write_schema(self, write_tool: FileWriteTool):
        schema = write_tool.get_schema()
        props = schema["function"]["parameters"]["properties"]
        assert "path" in props
        assert "content" in props
        assert "mode" in props

    def test_edit_schema(self, edit_tool: FileEditTool):
        schema = edit_tool.get_schema()
        required = schema["function"]["parameters"]["required"]
        assert "path" in required
        assert "old_text" in required
        assert "new_text" in required

    def test_search_schema(self, search_tool: FileSearchTool):
        schema = search_tool.get_schema()
        required = schema["function"]["parameters"]["required"]
        assert "query" in required
