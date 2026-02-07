"""
Storage module for Ungula.

Provides abstract storage interface and SQLite implementation.
"""

from .base import (
    AgentRecord,
    AgentRecordCreate,
    AgentStatus,
    Conversation,
    ConversationCreate,
    MemoryEntry,
    MemoryEntryCreate,
    Message,
    MessageCreate,
    StorageBackend,
    Task,
    TaskCreate,
    TaskStatus,
    User,
    UserCreate,
    UserInDB,
)
from .sqlite import SQLiteStorage

__all__ = [
    # Base interface
    "StorageBackend",
    # Users
    "User",
    "UserCreate",
    "UserInDB",
    # Conversations
    "Conversation",
    "ConversationCreate",
    # Messages
    "Message",
    "MessageCreate",
    # Tasks
    "Task",
    "TaskCreate",
    "TaskStatus",
    # Agents
    "AgentRecord",
    "AgentRecordCreate",
    "AgentStatus",
    # Memory
    "MemoryEntry",
    "MemoryEntryCreate",
    # Implementations
    "SQLiteStorage",
]
