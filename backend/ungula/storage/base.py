"""
Abstract storage interface for Ungula.

Defines the contract that all storage backends must implement.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# User types


class UserCreate(BaseModel):
    """Data for creating a user."""

    email: str
    password: str
    name: str | None = None


class User(BaseModel):
    """A user record."""

    id: UUID
    email: str
    name: str | None = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class UserInDB(User):
    """User with hashed password (for internal use)."""

    hashed_password: str


# Conversation types


class ConversationCreate(BaseModel):
    """Data for creating a conversation."""

    title: str | None = None
    user_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Conversation(BaseModel):
    """A conversation with messages."""

    id: UUID
    user_id: UUID | None = None
    title: str | None = None
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageCreate(BaseModel):
    """Data for creating a message."""

    conversation_id: UUID
    role: str  # user, assistant, system
    content: str
    agent_id: str | None = None
    model: str | None = None
    stage1: list[dict[str, Any]] | None = None  # Multi-model responses
    stage2: list[dict[str, Any]] | None = None  # Rankings
    stage3: dict[str, Any] | None = None  # Synthesis
    metadata: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    """A message in a conversation."""

    id: UUID
    conversation_id: UUID
    role: str
    content: str
    agent_id: str | None = None
    model: str | None = None
    stage1: list[dict[str, Any]] | None = None
    stage2: list[dict[str, Any]] | None = None
    stage3: dict[str, Any] | None = None
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskCreate(BaseModel):
    """Data for creating a task."""

    title: str
    description: str | None = None
    agent_id: str | None = None
    parent_task_id: UUID | None = None
    priority: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskStatus:
    """Task status constants."""

    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task(BaseModel):
    """A task for agents to execute."""

    id: UUID
    title: str
    description: str | None = None
    status: str = TaskStatus.PENDING
    agent_id: str | None = None
    parent_task_id: UUID | None = None
    priority: int = 0
    result: str | None = None
    error: str | None = None
    blocked_reason: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRecordCreate(BaseModel):
    """Data for creating an agent record."""

    id: str
    name: str
    type: str
    config: dict[str, Any] = Field(default_factory=dict)


class AgentStatus:
    """Agent status constants."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class AgentRecord(BaseModel):
    """A registered agent."""

    id: str
    name: str
    type: str
    status: str = AgentStatus.STOPPED
    config: dict[str, Any] = Field(default_factory=dict)
    last_heartbeat: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MemoryEntryCreate(BaseModel):
    """Data for creating a memory entry."""

    content: str
    memory_type: str  # fact, decision, preference, pattern, etc.
    level: str = "global"  # global, project, agent
    project_id: str | None = None
    agent_id: str | None = None
    source: str | None = None  # Where this memory came from
    embedding: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryEntry(BaseModel):
    """A memory entry."""

    id: UUID
    content: str
    memory_type: str
    level: str
    project_id: str | None = None
    agent_id: str | None = None
    source: str | None = None
    embedding: list[float] | None = None
    created_at: datetime
    accessed_at: datetime
    access_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


# Session types (for channel messaging)


class SessionCreate(BaseModel):
    """Data for creating a channel session."""

    channel: str
    contact_id: str
    contact_name: str | None = None
    conversation_id: UUID | None = None
    chat_type: str = "direct"  # direct, group
    metadata: dict[str, Any] = Field(default_factory=dict)


class Session(BaseModel):
    """A channel session (contact conversation)."""

    id: UUID
    channel: str
    contact_id: str
    contact_name: str | None = None
    conversation_id: UUID | None = None
    chat_type: str = "direct"
    active: bool = True
    last_activity: datetime
    message_count: int = 0
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class InboxMessageCreate(BaseModel):
    """Data for creating an inbox message."""

    session_id: UUID
    channel: str
    direction: str  # inbound, outbound
    sender_id: str
    sender_name: str | None = None
    content: str
    channel_message_id: str | None = None
    reply_to_id: str | None = None
    media_urls: list[str] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InboxMessage(BaseModel):
    """An inbox message from a channel."""

    id: UUID
    session_id: UUID
    channel: str
    direction: str
    sender_id: str
    sender_name: str | None = None
    content: str
    channel_message_id: str | None = None
    reply_to_id: str | None = None
    unread: bool = True
    media_urls: list[str] | None = None
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


# Token Usage types


class TokenUsageCreate(BaseModel):
    """Data for recording token usage."""

    conversation_id: UUID | None = None
    message_id: UUID | None = None
    user_id: UUID | None = None
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    """A token usage record."""

    id: UUID
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    user_id: UUID | None = None
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class StorageBackend(ABC):
    """Abstract base class for storage backends."""

    # Users

    @abstractmethod
    async def create_user(self, data: UserCreate) -> User:
        """Create a new user."""
        pass

    @abstractmethod
    async def get_user(self, user_id: UUID) -> User | None:
        """Get a user by ID."""
        pass

    @abstractmethod
    async def get_user_by_email(self, email: str) -> UserInDB | None:
        """Get a user by email (includes hashed password)."""
        pass

    @abstractmethod
    async def update_user(
        self, user_id: UUID, name: str | None = None, is_active: bool | None = None
    ) -> User | None:
        """Update user details."""
        pass

    # Conversations

    @abstractmethod
    async def create_conversation(self, data: ConversationCreate) -> Conversation:
        """Create a new conversation."""
        pass

    @abstractmethod
    async def get_conversation(self, conversation_id: UUID) -> Conversation | None:
        """Get a conversation by ID."""
        pass

    @abstractmethod
    async def list_conversations(
        self, user_id: UUID | None = None, limit: int = 50, offset: int = 0
    ) -> list[Conversation]:
        """List conversations with optional user filtering and pagination."""
        pass

    @abstractmethod
    async def update_conversation(
        self,
        conversation_id: UUID,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Conversation | None:
        """Update conversation title and/or metadata."""
        pass

    @abstractmethod
    async def delete_conversation(self, conversation_id: UUID) -> bool:
        """Delete a conversation and its messages."""
        pass

    # Messages

    @abstractmethod
    async def create_message(self, data: MessageCreate) -> Message:
        """Create a new message."""
        pass

    @abstractmethod
    async def get_message(self, message_id: UUID) -> Message | None:
        """Get a message by ID."""
        pass

    @abstractmethod
    async def list_messages(
        self, conversation_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Message]:
        """List messages in a conversation."""
        pass

    @abstractmethod
    async def count_messages_batch(
        self, conversation_ids: list[UUID]
    ) -> dict[UUID, int]:
        """Count messages for multiple conversations in a single query."""
        pass

    # Tasks

    @abstractmethod
    async def create_task(self, data: TaskCreate) -> Task:
        """Create a new task."""
        pass

    @abstractmethod
    async def get_task(self, task_id: UUID) -> Task | None:
        """Get a task by ID."""
        pass

    @abstractmethod
    async def list_tasks(
        self,
        status: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Task]:
        """List tasks with optional filtering."""
        pass

    @abstractmethod
    async def update_task_status(
        self,
        task_id: UUID,
        status: str,
        result: str | None = None,
        error: str | None = None,
        blocked_reason: str | None = None,
    ) -> Task | None:
        """Update task status."""
        pass

    # Agents

    @abstractmethod
    async def create_agent(self, data: AgentRecordCreate) -> AgentRecord:
        """Create or update an agent record."""
        pass

    @abstractmethod
    async def get_agent(self, agent_id: str) -> AgentRecord | None:
        """Get an agent by ID."""
        pass

    @abstractmethod
    async def list_agents(self) -> list[AgentRecord]:
        """List all agents."""
        pass

    @abstractmethod
    async def update_agent_status(
        self, agent_id: str, status: str
    ) -> AgentRecord | None:
        """Update agent status."""
        pass

    @abstractmethod
    async def update_agent_heartbeat(self, agent_id: str) -> AgentRecord | None:
        """Update agent last heartbeat time."""
        pass

    # Memory

    @abstractmethod
    async def create_memory(self, data: MemoryEntryCreate) -> MemoryEntry:
        """Create a new memory entry."""
        pass

    @abstractmethod
    async def get_memory(self, memory_id: UUID) -> MemoryEntry | None:
        """Get a memory entry by ID."""
        pass

    @abstractmethod
    async def search_memory(
        self,
        query_embedding: list[float] | None = None,
        memory_type: str | None = None,
        level: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        """Search memory entries."""
        pass

    @abstractmethod
    async def delete_memory(self, memory_id: UUID) -> bool:
        """Delete a memory entry."""
        pass

    # Sessions (channel messaging)

    @abstractmethod
    async def create_session(self, data: SessionCreate) -> Session:
        """Create a new session."""
        pass

    @abstractmethod
    async def get_session(self, session_id: UUID) -> Session | None:
        """Get a session by ID."""
        pass

    @abstractmethod
    async def get_session_by_contact(
        self, channel: str, contact_id: str
    ) -> Session | None:
        """Get a session by channel and contact ID."""
        pass

    @abstractmethod
    async def list_sessions(
        self,
        channel: str | None = None,
        active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Session]:
        """List sessions with optional filtering."""
        pass

    @abstractmethod
    async def update_session(
        self,
        session_id: UUID,
        active: bool | None = None,
        conversation_id: UUID | None = None,
        contact_name: str | None = None,
    ) -> Session | None:
        """Update session details."""
        pass

    @abstractmethod
    async def update_session_activity(
        self, session_id: UUID, increment_count: bool = True
    ) -> Session | None:
        """Update session last activity and optionally increment message count."""
        pass

    @abstractmethod
    async def delete_session(self, session_id: UUID) -> bool:
        """Delete a session and its messages."""
        pass

    # Inbox Messages

    @abstractmethod
    async def create_inbox_message(self, data: InboxMessageCreate) -> InboxMessage:
        """Create a new inbox message."""
        pass

    @abstractmethod
    async def get_inbox_message(self, message_id: UUID) -> InboxMessage | None:
        """Get an inbox message by ID."""
        pass

    @abstractmethod
    async def list_inbox_messages(
        self,
        session_id: UUID | None = None,
        channel: str | None = None,
        unread: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InboxMessage]:
        """List inbox messages with optional filtering."""
        pass

    @abstractmethod
    async def mark_messages_read(
        self,
        session_id: UUID | None = None,
        message_ids: list[UUID] | None = None,
    ) -> int:
        """Mark messages as read. Returns count of messages updated."""
        pass

    @abstractmethod
    async def count_unread_messages(
        self, channel: str | None = None, session_id: UUID | None = None
    ) -> int:
        """Count unread messages."""
        pass

    # Token Usage

    @abstractmethod
    async def record_token_usage(self, data: TokenUsageCreate) -> TokenUsage:
        """Record a token usage entry."""
        pass

    @abstractmethod
    async def get_token_usage_summary(
        self,
        user_id: UUID | None = None,
        conversation_id: UUID | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, Any]:
        """Get aggregated token usage summary."""
        pass

    # Lifecycle

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the storage backend (create tables, etc.)."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the storage backend."""
        pass
