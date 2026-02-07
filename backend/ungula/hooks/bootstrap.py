"""
Bootstrap first-run hook.

Detects when BOOTSTRAP.md exists and the workspace is fresh (template
content), enabling the frontend to trigger the onboarding conversation.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Strings that indicate a workspace file still has template content.
# These should be specific enough to avoid false positives on real content.
_TEMPLATE_MARKERS = [
    "[Your name",
    "your-name-here",
    "Describe yourself",
    "Fill in your",
    "TODO: ",
    "PLACEHOLDER",
]


def check_bootstrap_needed(workspace_dir: Path) -> bool:
    """Check if the workspace needs bootstrap (first-run setup).

    Returns True when BOOTSTRAP.md exists AND workspace files
    still contain template content.

    Args:
        workspace_dir: Path to the workspace directory.

    Returns:
        True if bootstrap is needed.
    """
    bootstrap_path = workspace_dir / "BOOTSTRAP.md"
    if not bootstrap_path.exists():
        return False

    content = bootstrap_path.read_text().strip()
    if not content:
        return False

    # Check if IDENTITY.md is still a template
    identity_path = workspace_dir / "IDENTITY.md"
    if identity_path.exists():
        identity_content = identity_path.read_text()
        for marker in _TEMPLATE_MARKERS:
            if marker in identity_content:
                return True

    # If IDENTITY.md doesn't exist, definitely needs bootstrap
    if not identity_path.exists():
        return True

    return False


async def run_bootstrap(workspace_dir: Path, agent_runner) -> dict:
    """Execute the bootstrap first-run ritual.

    Sends BOOTSTRAP.md content to the agent for processing.
    The agent should update IDENTITY.md, USER.md, SOUL.md
    and then delete BOOTSTRAP.md.

    Args:
        workspace_dir: Path to the workspace directory.
        agent_runner: AgentRunner instance.

    Returns:
        Dict with status and details.
    """
    bootstrap_path = workspace_dir / "BOOTSTRAP.md"

    if not bootstrap_path.exists():
        return {"status": "skipped", "reason": "no_bootstrap_file"}

    content = bootstrap_path.read_text().strip()
    if not content:
        return {"status": "skipped", "reason": "empty_content"}

    logger.info("Running bootstrap first-run ritual")

    try:
        from ..storage.base import ConversationCreate
        conv = await agent_runner.storage.create_conversation(
            ConversationCreate(title="[Bootstrap] First Run Setup")
        )

        response = await agent_runner.run(
            conv.id,
            content,
            stream=False,
        )

        result_content = response.content or ""
        logger.info("Bootstrap completed: %s", result_content[:200])

        return {
            "status": "completed",
            "conversation_id": str(conv.id),
            "response": result_content[:500],
        }

    except Exception as e:
        logger.error("Bootstrap execution failed: %s", e, exc_info=True)
        return {"status": "failed", "error": str(e)}
