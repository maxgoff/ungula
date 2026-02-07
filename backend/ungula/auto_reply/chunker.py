"""
Response chunker for channel message limits.

Splits long responses into paragraph-aware chunks that fit
within channel-specific character limits.
"""

import re


# Default limits per channel
CHANNEL_LIMITS: dict[str, int] = {
    "discord": 2000,
    "slack": 4000,
    "telegram": 4096,
    "signal": 10000,
    "imessage": 10000,
    "default": 2000,
}


def chunk_response(
    text: str,
    channel: str = "default",
    max_length: int | None = None,
) -> list[str]:
    """
    Split a response into chunks that fit channel limits.

    Attempts to split at paragraph boundaries, then sentence
    boundaries, then word boundaries as a last resort.

    Args:
        text: The full response text.
        channel: Channel name for limit lookup.
        max_length: Override the channel's default limit.

    Returns:
        List of text chunks, each within the limit.
    """
    limit = max_length or CHANNEL_LIMITS.get(channel, CHANNEL_LIMITS["default"])

    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        # Try to split at a paragraph boundary
        split_at = _find_paragraph_break(remaining, limit)

        # Fall back to sentence boundary
        if split_at is None or split_at < limit // 3:
            split_at = _find_sentence_break(remaining, limit)

        # Fall back to word boundary
        if split_at is None or split_at < limit // 3:
            split_at = _find_word_break(remaining, limit)

        # Last resort: hard cut
        if split_at is None or split_at < 1:
            split_at = limit

        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    return [c for c in chunks if c.strip()]


def _find_paragraph_break(text: str, limit: int) -> int | None:
    """Find the last paragraph break within the limit."""
    search_text = text[:limit]
    # Look for double newlines
    matches = list(re.finditer(r"\n\s*\n", search_text))
    if matches:
        return matches[-1].end()
    return None


def _find_sentence_break(text: str, limit: int) -> int | None:
    """Find the last sentence end within the limit."""
    search_text = text[:limit]
    # Look for sentence endings
    matches = list(re.finditer(r"[.!?]\s+", search_text))
    if matches:
        return matches[-1].end()
    # Try newline
    last_nl = search_text.rfind("\n")
    if last_nl > 0:
        return last_nl + 1
    return None


def _find_word_break(text: str, limit: int) -> int | None:
    """Find the last word break within the limit."""
    search_text = text[:limit]
    last_space = search_text.rfind(" ")
    if last_space > 0:
        return last_space + 1
    return None
