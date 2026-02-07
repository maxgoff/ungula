"""
Session memory hook.

Auto-saves conversation context to workspace memory files when a new
conversation starts (preserving context from the previous session).
"""

import logging
from datetime import date, datetime, UTC
from pathlib import Path
from uuid import UUID

from .slug_generator import generate_slug

logger = logging.getLogger(__name__)


def format_messages_for_summary(messages: list) -> str:
    """Format conversation messages into a readable text block."""
    lines = []
    for msg in messages:
        role = msg.role.upper()
        content = msg.content
        if len(content) > 500:
            content = content[:500] + "..."
        lines.append(f"**{role}**: {content}")
    return "\n\n".join(lines)


def format_memory_file(conversation_id: UUID, messages: list) -> str:
    """Format a memory file with conversation summary."""
    now = datetime.now(UTC)
    header = (
        f"# Session Memory\n\n"
        f"- **Date**: {now.strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"- **Conversation**: {conversation_id}\n"
        f"- **Messages**: {len(messages)}\n\n"
        f"## Conversation\n\n"
    )
    body = format_messages_for_summary(messages)
    return header + body + "\n"


async def save_session_memory(
    storage,
    conversation_id: UUID,
    workspace_dir: Path,
    registry=None,
) -> str | None:
    """Save conversation context to a workspace memory file.

    Args:
        storage: StorageBackend for loading messages.
        conversation_id: ID of the conversation to save.
        workspace_dir: Path to the workspace directory.
        registry: Optional ProviderRegistry for LLM slug generation.

    Returns:
        Filepath of the saved memory file, or None if skipped.
    """
    messages = await storage.list_messages(conversation_id, limit=15)
    if len(messages) < 2:
        return None  # Not enough content to save

    # Format messages for summary
    content = format_messages_for_summary(messages)

    # Generate semantic slug via LLM (with fallback)
    slug = await generate_slug(content, registry) if registry else None
    slug = slug or datetime.now(UTC).strftime("%H%M")

    # Write memory file
    memory_dir = workspace_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{date.today().isoformat()}-{slug}.md"
    filepath = memory_dir / filename

    filepath.write_text(format_memory_file(conversation_id, messages))
    logger.info("Saved session memory to %s", filepath)
    return str(filepath)
