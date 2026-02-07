"""
Context Window Pruning.

Trims large tool results before sending messages to the LLM,
reducing context pressure without losing critical information.

Two-level approach:
1. Soft trim: When context > soft_trim_ratio, trim large tool results to head+tail.
2. Hard clear: When context > hard_clear_ratio, replace old tool results entirely.
"""

import logging
from dataclasses import dataclass, field

from ..llm.base import Message as LLMMessage, MessageRole
from .token_counter import estimate_tokens

logger = logging.getLogger(__name__)


@dataclass
class PruningConfig:
    """Configuration for context pruning."""

    enabled: bool = True
    soft_trim_ratio: float = 0.3
    hard_clear_ratio: float = 0.5
    max_tool_result_chars: int = 4000
    head_chars: int = 1500
    tail_chars: int = 1500
    keep_recent_turns: int = 3
    min_prunable_chars: int = 50000


@dataclass
class PruningStats:
    """Statistics from a pruning pass."""

    soft_trimmed: int = 0
    hard_cleared: int = 0
    chars_saved: int = 0


def prune_tool_results(
    messages: list[LLMMessage],
    system_tokens: int,
    max_context_tokens: int,
    config: PruningConfig | None = None,
) -> PruningStats:
    """Prune tool results in-place based on context pressure.

    Args:
        messages: LLM message list (modified in place).
        system_tokens: Estimated tokens used by system prompt.
        max_context_tokens: Maximum context window size.
        config: Pruning configuration.

    Returns:
        PruningStats with counts of trimmed/cleared results.
    """
    if config is None:
        config = PruningConfig()

    if not config.enabled:
        return PruningStats()

    # Estimate current context usage
    history_tokens = sum(estimate_tokens(m.content or "") for m in messages)
    total_tokens = system_tokens + history_tokens
    fill_ratio = total_tokens / max_context_tokens if max_context_tokens > 0 else 0

    if fill_ratio < config.soft_trim_ratio:
        return PruningStats()

    stats = PruningStats()

    # Find prunable tool result messages (skip recent turns)
    prunable_indices = _find_prunable_indices(messages, config.keep_recent_turns)

    # Calculate total prunable content size
    total_prunable = sum(len(messages[i].content or "") for i in prunable_indices)
    if total_prunable < config.min_prunable_chars and fill_ratio < config.hard_clear_ratio:
        return stats

    use_hard_clear = fill_ratio >= config.hard_clear_ratio

    for idx in prunable_indices:
        msg = messages[idx]
        content = msg.content or ""

        if len(content) <= config.max_tool_result_chars:
            continue

        original_len = len(content)

        if use_hard_clear:
            # Hard clear: replace with placeholder
            messages[idx] = LLMMessage(
                role=msg.role,
                content="[Tool result cleared — context limit reached]",
                tool_call_id=msg.tool_call_id,
                name=msg.name,
            )
            stats.hard_cleared += 1
            stats.chars_saved += original_len - len(messages[idx].content)
        else:
            # Soft trim: keep head + tail
            head = content[:config.head_chars]
            tail = content[-config.tail_chars:]
            trimmed_chars = original_len - config.head_chars - config.tail_chars
            trimmed = f"{head}\n\n... [{trimmed_chars} characters trimmed] ...\n\n{tail}"
            messages[idx] = LLMMessage(
                role=msg.role,
                content=trimmed,
                tool_call_id=msg.tool_call_id,
                name=msg.name,
            )
            stats.soft_trimmed += 1
            stats.chars_saved += original_len - len(trimmed)

    if stats.soft_trimmed or stats.hard_cleared:
        logger.info(
            "Pruned tool results: %d soft-trimmed, %d hard-cleared, %d chars saved",
            stats.soft_trimmed,
            stats.hard_cleared,
            stats.chars_saved,
        )

    return stats


def _find_prunable_indices(
    messages: list[LLMMessage],
    keep_recent_turns: int,
) -> list[int]:
    """Find indices of tool result messages that can be pruned.

    Skips the most recent `keep_recent_turns` assistant turns
    and their associated tool messages (tool messages that appear
    between the Nth-from-end assistant message and the end).
    """
    if keep_recent_turns <= 0:
        return [i for i, m in enumerate(messages) if m.role == MessageRole.TOOL]

    # Count assistant turns from the end to find the cutoff.
    # The cutoff is the index of the Nth assistant message from the end.
    # Everything from that index onward (including preceding tool messages
    # in the same "turn") is protected.
    assistant_count = 0
    cutoff_idx = len(messages)

    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == MessageRole.ASSISTANT:
            assistant_count += 1
            if assistant_count >= keep_recent_turns:
                # Walk backwards from this assistant to include preceding
                # tool messages in the protected zone
                cutoff_idx = i
                while cutoff_idx > 0 and messages[cutoff_idx - 1].role == MessageRole.TOOL:
                    cutoff_idx -= 1
                break

    # Collect tool result message indices before the cutoff
    prunable = []
    for i in range(cutoff_idx):
        if messages[i].role == MessageRole.TOOL:
            prunable.append(i)

    return prunable
