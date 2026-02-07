"""
Directive parser for channel messages.

Parses slash-command style directives from message content:
  /model <name>   - Switch LLM model
  /think          - Show reasoning/chain of thought
  /status         - Show system status
  /compact        - Trigger context compaction
  /reset          - Reset conversation
  /help           - Show available commands
"""

import re
from dataclasses import dataclass


@dataclass
class Directive:
    """A parsed directive from a message."""

    command: str        # e.g., "model", "status"
    args: str           # Everything after the command
    original: str       # The full original text


# Known directives
KNOWN_DIRECTIVES = {
    "model", "think", "status", "compact",
    "reset", "help", "ping",
}


def parse_directive(text: str) -> Directive | None:
    """
    Parse a directive from message text.

    Returns a Directive if the text starts with a known /command,
    otherwise returns None.

    Args:
        text: The message text.

    Returns:
        Directive or None.
    """
    text = text.strip()
    if not text.startswith("/"):
        return None

    # Extract command and args
    match = re.match(r"^/(\w+)\s*(.*)", text, re.DOTALL)
    if not match:
        return None

    command = match.group(1).lower()
    args = match.group(2).strip()

    if command not in KNOWN_DIRECTIVES:
        return None

    return Directive(command=command, args=args, original=text)


class DirectiveParser:
    """
    Configurable directive parser.

    Supports custom directives and aliases.
    """

    def __init__(
        self,
        extra_directives: set[str] | None = None,
        aliases: dict[str, str] | None = None,
    ):
        self.directives = KNOWN_DIRECTIVES.copy()
        if extra_directives:
            self.directives.update(extra_directives)
        self.aliases = aliases or {}

    def parse(self, text: str) -> Directive | None:
        """Parse a directive, supporting aliases."""
        text = text.strip()
        if not text.startswith("/"):
            return None

        match = re.match(r"^/(\w+)\s*(.*)", text, re.DOTALL)
        if not match:
            return None

        command = match.group(1).lower()
        args = match.group(2).strip()

        # Resolve aliases
        command = self.aliases.get(command, command)

        if command not in self.directives:
            return None

        return Directive(command=command, args=args, original=text)
