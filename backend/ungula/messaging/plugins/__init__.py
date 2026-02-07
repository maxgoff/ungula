"""
Channel plugin architecture for Ungula messaging.

Provides composable middleware for typing indicators, reactions,
command gating, and mention requirements across all channels.
"""

from .command_gating import CommandGate
from .mention_gating import MentionGate
from .reactions import ReactionManager
from .typing import TypingManager

__all__ = [
    "CommandGate",
    "MentionGate",
    "ReactionManager",
    "TypingManager",
]
