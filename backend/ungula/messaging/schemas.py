"""
Pydantic schemas for messaging API.

Defines request/response models for channel, inbox, and session endpoints.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ============================================================================
# Channel Schemas
# ============================================================================


class ChannelInfo(BaseModel):
    """Information about a registered channel."""

    name: str
    display_name: str
    enabled: bool
    running: bool
    healthy: bool


class ChannelStatusResponse(BaseModel):
    """Channel status response."""

    channel: str
    healthy: bool
    running: bool
    last_start: datetime | None = None
    last_stop: datetime | None = None
    last_error: str | None = None
    last_inbound: datetime | None = None
    last_outbound: datetime | None = None
    message_count_in: int = 0
    message_count_out: int = 0


class ChannelListResponse(BaseModel):
    """List of channels response."""

    channels: list[ChannelInfo]
    status: dict[str, ChannelStatusResponse]


class ChannelHealthResponse(BaseModel):
    """Channel health check response."""

    channel: str
    healthy: bool
    error: str | None = None


# ============================================================================
# Inbox Schemas
# ============================================================================


class InboxMessageResponse(BaseModel):
    """Inbox message for API response."""

    id: str
    session_id: str
    channel: str
    direction: str  # "inbound" | "outbound"
    sender_id: str
    sender_name: str | None = None
    sender: str  # Alias for sender_name (frontend compatibility)
    content: str
    channel_message_id: str | None = None
    reply_to_id: str | None = None
    unread: bool
    created_at: datetime
    timestamp: str  # Relative time for frontend (e.g., "2 minutes ago")
    metadata: dict[str, Any] = Field(default_factory=dict)


class InboxListResponse(BaseModel):
    """List of inbox messages response."""

    messages: list[InboxMessageResponse]
    total: int
    unread_count: int


class InboxReplyRequest(BaseModel):
    """Request to reply to a session."""

    session_id: str
    content: str


class InboxReplyResponse(BaseModel):
    """Response after sending a reply."""

    success: bool
    message_id: str | None = None
    error: str | None = None


class MarkReadRequest(BaseModel):
    """Request to mark messages as read."""

    message_ids: list[str] | None = None  # None = mark all


# ============================================================================
# Session Schemas
# ============================================================================


class SessionResponse(BaseModel):
    """Session for API response."""

    id: str
    channel: str
    contact_id: str
    contact_name: str | None = None
    contact: str  # Alias for contact_name (frontend compatibility)
    conversation_id: str | None = None
    chat_type: str  # "direct" | "group"
    active: bool
    last_activity: datetime
    lastActivity: str  # Relative time for frontend
    message_count: int
    messageCount: int  # Alias for frontend
    last_message: str | None = None
    lastMessage: str | None = None  # Alias for frontend
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionListResponse(BaseModel):
    """List of sessions response."""

    sessions: list[SessionResponse]
    total: int
    active_count: int


class SessionDetailResponse(BaseModel):
    """Session detail with recent messages."""

    session: SessionResponse
    messages: list[InboxMessageResponse]


# ============================================================================
# Event Schemas (for SSE)
# ============================================================================


class NewMessageEvent(BaseModel):
    """SSE event for new inbox message."""

    type: str = "new_message"
    message: InboxMessageResponse


class SessionUpdateEvent(BaseModel):
    """SSE event for session update."""

    type: str = "session_update"
    session: SessionResponse


class ChannelStatusEvent(BaseModel):
    """SSE event for channel status change."""

    type: str = "channel_status"
    channel: str
    status: ChannelStatusResponse


# ============================================================================
# Helper Functions
# ============================================================================


def format_relative_time(dt: datetime) -> str:
    """
    Format a datetime as a relative time string.

    Args:
        dt: The datetime to format.

    Returns:
        A human-readable relative time string.
    """
    from datetime import UTC

    now = datetime.now(UTC)
    # Ensure dt is timezone-aware for comparison
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    diff = now - dt

    seconds = diff.total_seconds()

    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    else:
        return dt.strftime("%b %d, %Y")
