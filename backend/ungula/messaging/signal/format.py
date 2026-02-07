"""
Signal message formatting utilities.

Signal supports a subset of markdown-like formatting.
"""

import re

# Signal max message length (no official limit, but practical limit)
MAX_MESSAGE_LENGTH = 10000


def format_for_signal(text: str) -> str:
    """
    Format markdown text for Signal.

    Signal supports:
    - *bold*
    - _italic_
    - ~strikethrough~
    - ```code blocks```
    - No links, headers, etc.
    """
    # Convert **bold** to *bold* first
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)

    # Convert markdown headers to bold
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)

    # Convert ~~strike~~ to ~strike~
    text = re.sub(r"~~(.+?)~~", r"~\1~", text)

    # Strip markdown links to just text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    return text


def truncate_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> str:
    """Truncate message if too long."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 20] + "\n\n(truncated)"
