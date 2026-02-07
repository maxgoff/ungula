"""
Workspace write tool.

Allows the agent to update workspace files like USER.md, MEMORY.md, etc.
Enforces an allowlist to prevent critical files from being overwritten.
"""

import logging
import re
from pathlib import Path

from ungula.tools.base import Tool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

# Files the agent is allowed to write
_ALLOWED_FILES = frozenset({
    "USER.md",
    "MEMORY.md",
    "IDENTITY.md",
    "SOUL.md",
    "TOOLS.md",
    "HEARTBEAT.md",
    "BOOT.md",
})

# Pattern for daily memory files: memory/YYYY-MM-DD-slug.md
_MEMORY_FILE_PATTERN = re.compile(r"^memory/\d{4}-\d{2}-\d{2}[a-z0-9-]*\.md$")

# Files that must never be written by the agent
_DENIED_FILES = frozenset({
    "AGENTS.md",
    "BOOTSTRAP.md",
})


class WorkspaceWriteTool(Tool):
    """Update a workspace file or create/update a daily memory file."""

    name = "workspace_write"
    description = (
        "Update a workspace file (USER.md, MEMORY.md, IDENTITY.md, SOUL.md, "
        "TOOLS.md, HEARTBEAT.md, BOOT.md) or create/update a daily memory "
        "file (memory/YYYY-MM-DD-slug.md)"
    )
    parameters = [
        ToolParameter(
            name="file",
            description=(
                "Filename to write: USER.md, MEMORY.md, IDENTITY.md, SOUL.md, "
                "TOOLS.md, HEARTBEAT.md, BOOT.md, or memory/YYYY-MM-DD-slug.md"
            ),
        ),
        ToolParameter(
            name="content",
            description="Full file content to write",
        ),
        ToolParameter(
            name="mode",
            description="'write' to overwrite or 'append' to add to end",
            required=False,
        ),
    ]

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = workspace_dir

    async def execute(self, **kwargs) -> ToolResult:
        file_path = kwargs.get("file", "")
        content = kwargs.get("content", "")
        mode = kwargs.get("mode", "write")

        if not file_path:
            return ToolResult(success=False, output="", error="Missing 'file' parameter")
        if not content:
            return ToolResult(success=False, output="", error="Missing 'content' parameter")
        if mode not in ("write", "append"):
            return ToolResult(success=False, output="", error="Mode must be 'write' or 'append'")

        # Check denied list
        if file_path in _DENIED_FILES:
            return ToolResult(
                success=False,
                output="",
                error=f"Cannot write to {file_path}: this file is protected",
            )

        # Check allowed list (direct files or memory/* pattern)
        is_memory_file = _MEMORY_FILE_PATTERN.match(file_path)
        if file_path not in _ALLOWED_FILES and not is_memory_file:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Cannot write to '{file_path}'. Allowed files: "
                    f"{', '.join(sorted(_ALLOWED_FILES))}, or memory/YYYY-MM-DD-slug.md"
                ),
            )

        # Resolve path safely within workspace
        target = (self.workspace_dir / file_path).resolve()
        workspace_resolved = self.workspace_dir.resolve()

        try:
            target.relative_to(workspace_resolved)
        except ValueError:
            return ToolResult(
                success=False,
                output="",
                error="Path escapes workspace directory",
            )

        try:
            # Ensure parent directory exists (for memory/ subdirectory)
            target.parent.mkdir(parents=True, exist_ok=True)

            if mode == "append":
                existing = target.read_text() if target.exists() else ""
                target.write_text(existing + content)
            else:
                target.write_text(content)

            logger.info("Wrote workspace file: %s (%d bytes, mode=%s)", file_path, len(content), mode)
            return ToolResult(
                success=True,
                output=f"Successfully wrote {len(content)} bytes to {file_path}",
            )

        except Exception as e:
            logger.error("Failed to write workspace file %s: %s", file_path, e)
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to write file: {e}",
            )
