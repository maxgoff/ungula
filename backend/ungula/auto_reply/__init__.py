"""Auto-reply pipeline for channel messages."""

from .directives import DirectiveParser, parse_directive
from .dispatch import AutoReplyDispatcher

__all__ = ["AutoReplyDispatcher", "DirectiveParser", "parse_directive"]
