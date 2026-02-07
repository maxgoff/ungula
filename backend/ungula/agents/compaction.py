"""
Context Window Compaction.

When conversation history approaches the context window limit, this module
summarizes older messages via the LLM and replaces them with a compact
summary. This preserves important context while staying within token limits.

Strategy:
1. Estimate tokens for system prompt + history + headroom.
2. If over threshold (based on history budget), split history into older
   (to compact) and recent (to keep).
3. Summarize the older portion via the LLM, including tool usage tracking.
4. Return the summary as a system-level note plus the recent messages.
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from ..llm.base import CompletionRequest, Message as LLMMessage, MessageRole
from ..llm.registry import ProviderRegistry
from ..storage.base import StorageBackend
from .token_counter import estimate_tokens

logger = logging.getLogger(__name__)


@dataclass
class CompactionConfig:
    """Configuration for context compaction."""

    max_context_tokens: int = 200_000
    max_history_share: float = 0.5
    reserve_tokens_floor: int = 20_000
    min_recent_messages: int = 6
    safety_margin: float = 1.2
    summary_max_tokens: int = 2000


# Default config for backwards compatibility
_DEFAULT_CONFIG = CompactionConfig()

# Legacy module-level constants (used by existing tests and callers)
DEFAULT_MAX_CONTEXT_TOKENS = 100_000
COMPACTION_THRESHOLD_RATIO = 0.4
MIN_RECENT_MESSAGES = _DEFAULT_CONFIG.min_recent_messages
SAFETY_MARGIN = _DEFAULT_CONFIG.safety_margin

SUMMARY_SYSTEM_PROMPT = (
    "You are a conversation summarizer. Summarize the following conversation "
    "history into a concise but informative summary. Preserve: key decisions, "
    "user preferences, important facts, action items, and any context that "
    "would be needed to continue the conversation naturally.\n\n"
    "If tools were used, note which tools were called and what files or "
    "resources were accessed or modified. Be concise -- target roughly "
    "1/4 the length of the original."
)


async def compact_if_needed(
    messages: list,
    system_prompt: str,
    *,
    registry: ProviderRegistry,
    storage: StorageBackend,
    conversation_id: UUID,
    provider: str | None = None,
    max_context_tokens: int | None = None,
    config: CompactionConfig | None = None,
) -> list | tuple[list, str]:
    """Compact conversation history if it exceeds the token threshold.

    Uses a history budget (max_history_share * max_context_tokens) to decide
    when compaction is needed, and adaptively chooses a split point based
    on how far over budget the history is.

    Args:
        messages: The full message history (storage Message objects).
        system_prompt: The current system prompt text.
        registry: LLM provider registry for summarization.
        storage: Storage backend.
        conversation_id: The conversation being compacted.
        provider: LLM provider to use for summarization.
        max_context_tokens: Override max context tokens (deprecated, use config).
        config: Compaction configuration.

    Returns:
        The (possibly compacted) message list. If compaction occurred,
        returns a tuple of (recent_messages, summary).
    """
    if config is None:
        config = _DEFAULT_CONFIG

    effective_max = max_context_tokens or config.max_context_tokens

    if len(messages) <= config.min_recent_messages:
        return messages

    # Estimate current token usage
    system_tokens = estimate_tokens(system_prompt)
    history_tokens = sum(estimate_tokens(m.content) for m in messages)

    # Calculate history budget
    history_budget = int(effective_max * config.max_history_share)
    # Ensure we always leave room for new content
    available_for_history = effective_max - system_tokens - config.reserve_tokens_floor
    history_budget = min(history_budget, available_for_history)

    threshold = int(history_budget / config.safety_margin)

    if history_tokens <= threshold:
        logger.debug(
            "No compaction needed: %d history tokens (budget %d, threshold %d)",
            history_tokens, history_budget, threshold,
        )
        return messages

    logger.info(
        "Compaction triggered: %d history tokens exceeds threshold %d "
        "(budget=%d) for conversation %s",
        history_tokens, threshold, history_budget, conversation_id,
    )

    # Adaptive split point: compact proportionally to how far over budget we are
    overage_ratio = history_tokens / threshold  # e.g. 1.5 means 50% over
    # Compact more aggressively when further over budget
    compact_fraction = min(0.8, 0.4 + 0.2 * (overage_ratio - 1.0))
    split_point = int(len(messages) * compact_fraction)

    # Enforce min_recent_messages
    split_point = min(split_point, len(messages) - config.min_recent_messages)
    split_point = max(split_point, 1)

    older_messages = messages[:split_point]
    recent_messages = messages[split_point:]

    # Summarize older messages (with tool tracking)
    summary = await _summarize_messages(
        older_messages, registry, provider, config.summary_max_tokens
    )

    if not summary:
        logger.warning("Compaction failed (empty summary), keeping full history")
        return messages

    # Store the summary in conversation metadata for persistence
    older_tokens = sum(estimate_tokens(m.content) for m in older_messages)
    summary_tokens = estimate_tokens(summary)

    try:
        conversation = await storage.get_conversation(conversation_id)
        if conversation:
            metadata = conversation.metadata or {}
            metadata["compaction_summary"] = summary
            metadata["compacted_message_count"] = len(older_messages)
            metadata["compacted_tokens_saved"] = older_tokens - summary_tokens
            await storage.update_conversation(conversation_id, metadata=metadata)
    except Exception as e:
        logger.warning("Failed to persist compaction summary: %s", e)

    logger.info(
        "Compacted %d messages into summary (%d -> %d tokens, saved %d)",
        len(older_messages),
        older_tokens,
        summary_tokens,
        older_tokens - summary_tokens,
    )

    return recent_messages, summary


async def _summarize_messages(
    messages: list,
    registry: ProviderRegistry,
    provider: str | None = None,
    max_tokens: int = 2000,
) -> str | None:
    """Summarize a list of messages using the LLM.

    Includes tool usage tracking in the summary prompt.

    Args:
        messages: Messages to summarize.
        registry: LLM provider registry.
        provider: Provider to use.
        max_tokens: Max tokens for the summary response.

    Returns:
        Summary text, or None on failure.
    """
    # Build conversation text for summarization
    lines = []
    tool_names_used: set[str] = set()

    for msg in messages:
        role = msg.role.upper()
        lines.append(f"[{role}]: {msg.content}")

        # Track tool usage from metadata
        metadata = getattr(msg, "metadata", None) or {}
        if isinstance(metadata, dict):
            tool_calls = metadata.get("tool_calls", [])
            for tc in tool_calls:
                if isinstance(tc, dict) and "name" in tc:
                    tool_names_used.add(tc["name"])

    conversation_text = "\n\n".join(lines)

    # Add tool tracking context
    if tool_names_used:
        conversation_text += f"\n\n[Tools used in this segment: {', '.join(sorted(tool_names_used))}]"

    request = CompletionRequest(
        messages=[
            LLMMessage(role=MessageRole.SYSTEM, content=SUMMARY_SYSTEM_PROMPT),
            LLMMessage(role=MessageRole.USER, content=conversation_text),
        ],
        temperature=0.3,
        max_tokens=max_tokens,
        stream=False,
    )

    try:
        response = await registry.complete(request, provider=provider)
        return response.content
    except Exception as e:
        logger.error("Failed to generate compaction summary: %s", e)
        return None
