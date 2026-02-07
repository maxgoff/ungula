"""
Boot execution hook.

Runs BOOT.md tasks during application startup by sending
the content to the agent runner for processing.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BOOT_SYSTEM_PROMPT = (
    "You are running a startup boot check. Follow the instructions in "
    "BOOT.md exactly. If nothing needs attention, reply with BOOT_OK."
)


async def run_boot_tasks(workspace_dir: Path, agent_runner) -> dict:
    """Execute boot tasks from BOOT.md.

    Reads BOOT.md from the workspace directory and sends its content
    to the agent runner for processing.

    Args:
        workspace_dir: Path to the workspace directory.
        agent_runner: AgentRunner instance for processing.

    Returns:
        Dict with status ('skipped', 'completed', 'failed') and details.
    """
    boot_path = workspace_dir / "BOOT.md"

    if not boot_path.exists():
        logger.info("No BOOT.md found, skipping boot tasks")
        return {"status": "skipped", "reason": "no_boot_file"}

    content = boot_path.read_text().strip()

    # Skip if empty or only comments
    meaningful_lines = [
        line for line in content.split("\n")
        if line.strip() and not line.strip().startswith("#")
    ]
    if not meaningful_lines:
        logger.info("BOOT.md is empty or only comments, skipping")
        return {"status": "skipped", "reason": "empty_content"}

    logger.info("Running boot tasks from BOOT.md (%d lines)", len(meaningful_lines))

    try:
        # Create a dedicated boot conversation
        from ..storage.base import ConversationCreate
        conv = await agent_runner.storage.create_conversation(
            ConversationCreate(title="[Boot] Startup Tasks")
        )

        # Run the agent with BOOT.md content
        response = await agent_runner.run(
            conv.id,
            f"Execute the following boot tasks:\n\n{content}",
            stream=False,
        )

        result_content = response.content or ""
        status = "completed" if "BOOT_OK" not in result_content else "completed_ok"
        logger.info("Boot tasks %s: %s", status, result_content[:200])

        return {
            "status": status,
            "conversation_id": str(conv.id),
            "response": result_content[:500],
        }

    except Exception as e:
        logger.error("Boot task execution failed: %s", e, exc_info=True)
        return {"status": "failed", "error": str(e)}
