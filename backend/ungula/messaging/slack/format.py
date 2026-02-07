"""
Slack message formatting utilities.

Converts markdown-formatted text to Slack's mrkdwn format
and handles Block Kit conversion for richer messages.
"""

import re

# Maximum message length for Slack
MAX_MESSAGE_LENGTH = 4000


def markdown_to_mrkdwn(text: str) -> str:
    """
    Convert standard markdown to Slack mrkdwn format.

    Key differences:
    - Bold: **text** -> *text*
    - Italic: *text* -> _text_
    - Code blocks: ```lang -> ```
    - Headers: ## Header -> *Header*
    - Links: [text](url) -> <url|text>
    """
    # Convert bold first: **text** -> *text*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)

    # Convert headers to bold
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)

    # Convert links: [text](url) -> <url|text>
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", text)

    # Convert italic (single asterisk that's not already bold): _text_ stays
    # Slack uses _ for italic natively

    # Convert strikethrough: ~~text~~ -> ~text~
    text = re.sub(r"~~(.+?)~~", r"~\1~", text)

    return text


def truncate_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> str:
    """Truncate a message to fit Slack's limits."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 20] + "\n\n_(truncated)_"


def to_blocks(text: str) -> list[dict]:
    """
    Convert text to Slack Block Kit blocks.

    Wraps text in a section block. For longer text, splits
    into multiple blocks.
    """
    text = markdown_to_mrkdwn(text)

    # Split into chunks if too long for a single block (3000 char limit)
    chunks = []
    while text:
        if len(text) <= 3000:
            chunks.append(text)
            break
        # Find a good split point
        split_at = text.rfind("\n", 0, 3000)
        if split_at == -1:
            split_at = 3000
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()

    blocks = []
    for chunk in chunks:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": chunk,
            },
        })

    return blocks
