"""
Token counting utilities for context window management.

Uses tiktoken for OpenAI-compatible models and a character-based
heuristic fallback for other providers.
"""

import logging

logger = logging.getLogger(__name__)

# Cache tiktoken encoding to avoid repeated initialization
_encoding = None


def _get_tiktoken_encoding():
    """Get or create the tiktoken encoding (cl100k_base, used by GPT-4/Claude)."""
    global _encoding
    if _encoding is None:
        try:
            import tiktoken
            _encoding = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            logger.debug("tiktoken not available, using heuristic: %s", e)
            _encoding = False  # Sentinel: tried and failed
    return _encoding if _encoding is not False else None


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in a text string.

    Uses tiktoken (cl100k_base) when available, falls back to a
    4-characters-per-token heuristic.

    Args:
        text: The text to count tokens for.

    Returns:
        Estimated token count.
    """
    if not text:
        return 0

    encoding = _get_tiktoken_encoding()
    if encoding is not None:
        return len(encoding.encode(text))

    # Heuristic fallback: ~4 characters per token
    return max(1, len(text) // 4)


def estimate_messages_tokens(messages: list[dict]) -> int:
    """Estimate total tokens across a list of message dicts.

    Each message should have at minimum a 'content' key.
    Adds overhead per message for role tokens (~4 tokens each).

    Args:
        messages: List of message dicts with 'content' and 'role' keys.

    Returns:
        Estimated total token count.
    """
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        total += estimate_tokens(content)
        total += 4  # Overhead for role, delimiters
    total += 2  # Priming tokens
    return total
