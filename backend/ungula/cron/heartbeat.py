"""
Heartbeat agent check-in system.

Periodic task that reads HEARTBEAT.md from workspace and
executes defined check-in tasks. Optionally triggers memory
review when recent memory files exist.
"""

import logging
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


async def run_heartbeat(workspace_dir: Path) -> dict:
    """
    Execute heartbeat tasks from HEARTBEAT.md.

    Reads the workspace HEARTBEAT.md file and returns its
    content as tasks to be processed by the agent.

    Returns:
        Dict with 'content' (heartbeat text) and 'tasks' (parsed items).
    """
    heartbeat_path = workspace_dir / "HEARTBEAT.md"

    if not heartbeat_path.exists():
        return {"content": None, "tasks": []}

    content = heartbeat_path.read_text().strip()
    if not content:
        return {"content": None, "tasks": []}

    # Parse checklist items from the heartbeat file
    tasks = []
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("- [ ]"):
            tasks.append(line[5:].strip())
        elif line.startswith("- [x]"):
            # Already completed, skip
            continue

    return {
        "content": content,
        "tasks": tasks,
    }


async def build_heartbeat_prompt(workspace_dir: Path) -> str | None:
    """Build heartbeat prompt with HEARTBEAT.md + memory review if due.

    Combines the heartbeat checklist tasks with optional memory review
    instructions when recent memory files exist.

    Args:
        workspace_dir: Path to the workspace directory.

    Returns:
        Combined prompt string, or None if nothing to do.
    """
    result = await run_heartbeat(workspace_dir)

    parts = []
    if result["tasks"]:
        parts.append("## Heartbeat Tasks\n" + result["content"])

    # Check if memory review is needed (any memory files in last 3 days)
    memory_dir = workspace_dir / "memory"
    if memory_dir.exists():
        recent_cutoff = date.today() - timedelta(days=3)
        recent_files = []
        for f in memory_dir.glob("*.md"):
            # Parse date from filename (YYYY-MM-DD-slug.md)
            try:
                file_date = date.fromisoformat(f.name[:10])
                if file_date >= recent_cutoff:
                    recent_files.append(f.name)
            except ValueError:
                continue

        if recent_files:
            parts.append(
                "## Memory Review\n"
                "Review recent memory/YYYY-MM-DD*.md files. "
                "Distill significant learnings into MEMORY.md. "
                "Remove outdated info from MEMORY.md.\n\n"
                f"Recent files: {', '.join(sorted(recent_files))}"
            )

    if not parts:
        return None  # Nothing to do
    return "\n\n".join(parts)
