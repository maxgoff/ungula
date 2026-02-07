"""
File operation tools: read, write, edit, search.

All paths are resolved relative to the workspace directory and
validated to prevent path traversal.
"""

import logging
import os
from pathlib import Path
from typing import Any

from ungula.config import FileToolsConfig
from ungula.tools.base import Tool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


def _resolve_safe_path(workspace: Path, user_path: str) -> Path | None:
    """Resolve a user-provided path safely within the workspace.

    Returns the resolved path if safe, None if it escapes the workspace.
    """
    # Join with workspace root
    target = (workspace / user_path).resolve()
    workspace_resolved = workspace.resolve()

    # Verify the resolved path is within the workspace
    try:
        target.relative_to(workspace_resolved)
    except ValueError:
        return None

    # Reject symlinks that point outside workspace
    if target.is_symlink():
        real = target.resolve()
        try:
            real.relative_to(workspace_resolved)
        except ValueError:
            return None

    return target


def _check_extension(path: Path, denied: list[str]) -> str | None:
    """Check if file extension is denied. Returns error message or None."""
    for ext in denied:
        if path.name.endswith(ext):
            return f"Access denied: {ext} files are blocked"
    return None


class FileReadTool(Tool):
    """Read a file from the workspace."""

    name = "file_read"
    description = "Read the contents of a file in the workspace, with optional line range"
    parameters = [
        ToolParameter(name="path", description="File path relative to workspace", required=True),
        ToolParameter(name="offset", description="Starting line number (1-based)", type="integer", required=False),
        ToolParameter(name="limit", description="Number of lines to read", type="integer", required=False),
    ]

    def __init__(self, workspace_dir: Path, config: FileToolsConfig):
        self.workspace_dir = workspace_dir
        self.config = config

    async def execute(self, **kwargs: Any) -> ToolResult:
        user_path = kwargs.get("path", "")
        if not user_path:
            return ToolResult(success=False, output="", error="path is required")

        target = _resolve_safe_path(self.workspace_dir, user_path)
        if target is None:
            return ToolResult(success=False, output="", error="Path is outside workspace")

        ext_error = _check_extension(target, self.config.denied_extensions)
        if ext_error:
            return ToolResult(success=False, output="", error=ext_error)

        if not target.exists():
            return ToolResult(success=False, output="", error=f"File not found: {user_path}")
        if not target.is_file():
            return ToolResult(success=False, output="", error=f"Not a file: {user_path}")

        # Check file size
        size = target.stat().st_size
        if size > self.config.max_file_size:
            return ToolResult(
                success=False, output="",
                error=f"File too large ({size} bytes, max {self.config.max_file_size})",
            )

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Read error: {e}")

        # Apply line range
        offset = kwargs.get("offset")
        limit = kwargs.get("limit")

        if offset or limit:
            lines = content.splitlines(keepends=True)
            start = max(0, (int(offset) - 1)) if offset else 0
            end = start + int(limit) if limit else len(lines)
            selected = lines[start:end]

            # Format with line numbers
            numbered = []
            for i, line in enumerate(selected, start=start + 1):
                numbered.append(f"{i:>6}\t{line.rstrip()}")
            content = "\n".join(numbered)
        else:
            # Full file with line numbers
            lines = content.splitlines()
            numbered = [f"{i:>6}\t{line}" for i, line in enumerate(lines, 1)]
            content = "\n".join(numbered)

        return ToolResult(
            success=True,
            output=content,
            data={"path": str(target.relative_to(self.workspace_dir)), "size": size},
        )


class FileWriteTool(Tool):
    """Write content to a file in the workspace."""

    name = "file_write"
    description = "Write or append content to a file in the workspace. Creates parent directories if needed."
    parameters = [
        ToolParameter(name="path", description="File path relative to workspace", required=True),
        ToolParameter(name="content", description="Content to write", required=True),
        ToolParameter(
            name="mode", description="Write mode: 'write' (overwrite) or 'append'",
            required=False, default="write",
        ),
    ]

    def __init__(self, workspace_dir: Path, config: FileToolsConfig):
        self.workspace_dir = workspace_dir
        self.config = config

    async def execute(self, **kwargs: Any) -> ToolResult:
        user_path = kwargs.get("path", "")
        content = kwargs.get("content", "")
        mode = kwargs.get("mode", "write")

        if not user_path:
            return ToolResult(success=False, output="", error="path is required")
        if content is None:
            return ToolResult(success=False, output="", error="content is required")

        target = _resolve_safe_path(self.workspace_dir, user_path)
        if target is None:
            return ToolResult(success=False, output="", error="Path is outside workspace")

        ext_error = _check_extension(target, self.config.denied_extensions)
        if ext_error:
            return ToolResult(success=False, output="", error=ext_error)

        # Check content size
        if len(content.encode("utf-8")) > self.config.max_file_size:
            return ToolResult(success=False, output="", error="Content exceeds max file size")

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if mode == "append":
                with open(target, "a", encoding="utf-8") as f:
                    f.write(content)
            else:
                target.write_text(content, encoding="utf-8")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Write error: {e}")

        rel_path = str(target.relative_to(self.workspace_dir))
        return ToolResult(
            success=True,
            output=f"Wrote {len(content)} chars to {rel_path}",
            data={"path": rel_path, "bytes": len(content.encode("utf-8"))},
        )


class FileEditTool(Tool):
    """Find-and-replace text in a workspace file."""

    name = "file_edit"
    description = "Find and replace text in a workspace file. Fails if old_text is not found or not unique (unless replace_all=true)."
    parameters = [
        ToolParameter(name="path", description="File path relative to workspace", required=True),
        ToolParameter(name="old_text", description="Text to find", required=True),
        ToolParameter(name="new_text", description="Replacement text", required=True),
        ToolParameter(
            name="replace_all", description="Replace all occurrences (default false)",
            type="boolean", required=False, default=False,
        ),
    ]

    def __init__(self, workspace_dir: Path, config: FileToolsConfig):
        self.workspace_dir = workspace_dir
        self.config = config

    async def execute(self, **kwargs: Any) -> ToolResult:
        user_path = kwargs.get("path", "")
        old_text = kwargs.get("old_text", "")
        new_text = kwargs.get("new_text", "")
        replace_all = kwargs.get("replace_all", False)

        if not user_path or not old_text:
            return ToolResult(success=False, output="", error="path and old_text are required")

        target = _resolve_safe_path(self.workspace_dir, user_path)
        if target is None:
            return ToolResult(success=False, output="", error="Path is outside workspace")

        ext_error = _check_extension(target, self.config.denied_extensions)
        if ext_error:
            return ToolResult(success=False, output="", error=ext_error)

        if not target.exists() or not target.is_file():
            return ToolResult(success=False, output="", error=f"File not found: {user_path}")

        try:
            content = target.read_text(encoding="utf-8")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Read error: {e}")

        count = content.count(old_text)
        if count == 0:
            return ToolResult(success=False, output="", error="old_text not found in file")

        if count > 1 and not replace_all:
            return ToolResult(
                success=False, output="",
                error=f"old_text found {count} times — use replace_all=true or provide more context",
            )

        if replace_all:
            new_content = content.replace(old_text, new_text)
        else:
            new_content = content.replace(old_text, new_text, 1)

        try:
            target.write_text(new_content, encoding="utf-8")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Write error: {e}")

        rel_path = str(target.relative_to(self.workspace_dir))
        return ToolResult(
            success=True,
            output=f"Replaced {count if replace_all else 1} occurrence(s) in {rel_path}",
            data={"path": rel_path, "replacements": count if replace_all else 1},
        )


class FileSearchTool(Tool):
    """Search for text across workspace files."""

    name = "file_search"
    description = "Search for text content across workspace files. Returns matching lines with file paths and line numbers."
    parameters = [
        ToolParameter(name="query", description="Text or pattern to search for", required=True),
        ToolParameter(name="glob", description="Glob pattern to filter files (e.g. '*.py', '**/*.md')", required=False),
        ToolParameter(name="max_results", description="Maximum results to return (default 20)", type="integer", required=False, default=20),
    ]

    def __init__(self, workspace_dir: Path, config: FileToolsConfig):
        self.workspace_dir = workspace_dir
        self.config = config

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "")
        glob_pattern = kwargs.get("glob", "**/*")
        max_results = int(kwargs.get("max_results", 20))

        if not query:
            return ToolResult(success=False, output="", error="query is required")

        if not glob_pattern:
            glob_pattern = "**/*"

        matches = []
        try:
            for path in self.workspace_dir.glob(glob_pattern):
                if not path.is_file():
                    continue

                # Skip denied extensions
                if _check_extension(path, self.config.denied_extensions):
                    continue

                # Skip binary/large files
                try:
                    size = path.stat().st_size
                    if size > self.config.max_file_size or size == 0:
                        continue
                except OSError:
                    continue

                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue

                rel_path = str(path.relative_to(self.workspace_dir))
                for i, line in enumerate(content.splitlines(), 1):
                    if query.lower() in line.lower():
                        matches.append(f"{rel_path}:{i}:{line.strip()}")
                        if len(matches) >= max_results:
                            break
                if len(matches) >= max_results:
                    break
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Search error: {e}")

        if not matches:
            return ToolResult(success=True, output="No matches found", data={"count": 0})

        return ToolResult(
            success=True,
            output="\n".join(matches),
            data={"count": len(matches)},
        )
