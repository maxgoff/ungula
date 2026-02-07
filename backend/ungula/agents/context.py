"""
Context assembly for agent invocations.

Builds system prompts from workspace files and assembles conversation history.
Delegates to the modular prompt_sections system for section-based prompts.
"""

from pathlib import Path
from uuid import UUID

from ..llm.base import Message as LLMMessage, MessageRole
from ..storage.base import Message, StorageBackend
from .prompt_sections import PromptMode, build_prompt_from_workspace


# Workspace files to include in system prompt (filename, required)
WORKSPACE_FILES = [
    ("SOUL.md", True),
    ("AGENTS.md", False),
    ("IDENTITY.md", False),
    ("USER.md", False),
]


# Map session type strings to PromptMode
_SESSION_TYPE_MAP = {
    "main": PromptMode.FULL,
    "subagent": PromptMode.SUBAGENT,
    "group": PromptMode.SUBAGENT,
}


class SystemPromptBuilder:
    """
    Builds system prompts from workspace files.

    Delegates to the modular prompt_sections system for
    section-based, priority-ordered prompt assembly.
    """

    def __init__(
        self,
        workspace_dir: Path,
        skills_prompt: str | None = None,
        tools_info: list[dict[str, str]] | None = None,
        memory_context: list[str] | None = None,
        mode: PromptMode = PromptMode.FULL,
        session_type: str | None = None,
    ):
        self.workspace_dir = workspace_dir
        self.skills_prompt = skills_prompt
        self.tools_info = tools_info
        self.memory_context = memory_context
        # session_type overrides mode if provided
        if session_type:
            self.mode = _SESSION_TYPE_MAP.get(session_type, PromptMode.FULL)
        else:
            self.mode = mode

    def build(self) -> str:
        """
        Assemble system prompt from modular sections.

        Returns:
            The assembled system prompt string.
        """
        return build_prompt_from_workspace(
            workspace_dir=self.workspace_dir,
            mode=self.mode,
            skills_prompt=self.skills_prompt,
            tools_info=self.tools_info,
            memory_context=self.memory_context,
        )


async def build_context(
    storage: StorageBackend,
    conversation_id: UUID,
    workspace_dir: Path,
    max_history: int = 50,
    model: str | None = None,
    provider: str | None = None,
) -> tuple[str, list[LLMMessage]]:
    """
    Build complete context for an agent invocation.

    Args:
        storage: Storage backend for loading conversation history.
        conversation_id: ID of the conversation.
        workspace_dir: Path to workspace directory.
        max_history: Maximum number of history messages to include.
        model: Optional model override.
        provider: Optional provider override.

    Returns:
        Tuple of (system_prompt, history_messages).
    """
    # Build system prompt from workspace files
    builder = SystemPromptBuilder(workspace_dir)
    system_prompt = builder.build()

    # Load conversation history
    messages = await storage.list_messages(
        conversation_id,
        limit=max_history,
    )

    # Convert to LLM message format
    llm_messages = _convert_to_llm_messages(messages)

    return system_prompt, llm_messages


def _convert_to_llm_messages(messages: list[Message]) -> list[LLMMessage]:
    """
    Convert storage messages to LLM message format.

    Only includes user and assistant messages (not system).
    """
    result = []
    for msg in messages:
        if msg.role in ("user", "assistant"):
            result.append(
                LLMMessage(
                    role=MessageRole(msg.role),
                    content=msg.content,
                )
            )
    return result
