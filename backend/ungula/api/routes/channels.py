"""
Channel API Routes.

Provides endpoints for channel management, inbox, and sessions.
"""

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...auth import get_current_user
from ...storage.base import User
from ...messaging.registry import ChannelRegistry
from ...messaging.router import MessageRouter
from ...messaging.schemas import (
    ChannelHealthResponse,
    ChannelInfo,
    ChannelListResponse,
    ChannelStatusResponse,
    InboxListResponse,
    InboxMessageResponse,
    InboxReplyRequest,
    InboxReplyResponse,
    SessionDetailResponse,
    SessionListResponse,
    SessionResponse,
    format_relative_time,
)
from ...messaging.session import SessionManager
from ...storage.base import InboxMessage, Session, StorageBackend

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Helper Functions
# ============================================================================


def get_storage(request: Request) -> StorageBackend:
    """Get storage from app state."""
    return request.app.state.storage


def get_session_manager(request: Request) -> SessionManager:
    """Get session manager from app state."""
    if not hasattr(request.app.state, "session_manager"):
        # Create on demand with storage
        storage = get_storage(request)
        request.app.state.session_manager = SessionManager(storage=storage)
    return request.app.state.session_manager


def get_channel_registry(request: Request) -> ChannelRegistry | None:
    """Get channel registry from app state (may not exist)."""
    return getattr(request.app.state, "channel_registry", None)


def get_message_router(request: Request) -> MessageRouter | None:
    """Get message router from app state (may not exist)."""
    return getattr(request.app.state, "message_router", None)


def session_to_response(session: Session, last_message: str | None = None) -> SessionResponse:
    """Convert Session to API response."""
    return SessionResponse(
        id=str(session.id),
        channel=session.channel,
        contact_id=session.contact_id,
        contact_name=session.contact_name,
        contact=session.contact_name or session.contact_id,
        conversation_id=str(session.conversation_id) if session.conversation_id else None,
        chat_type=session.chat_type,
        active=session.active,
        last_activity=session.last_activity,
        lastActivity=format_relative_time(session.last_activity),
        message_count=session.message_count,
        messageCount=session.message_count,
        last_message=last_message,
        lastMessage=last_message,
        metadata=session.metadata,
    )


def inbox_message_to_response(msg: InboxMessage) -> InboxMessageResponse:
    """Convert InboxMessage to API response."""
    return InboxMessageResponse(
        id=str(msg.id),
        session_id=str(msg.session_id),
        channel=msg.channel,
        direction=msg.direction,
        sender_id=msg.sender_id,
        sender_name=msg.sender_name,
        sender=msg.sender_name or msg.sender_id,
        content=msg.content,
        channel_message_id=msg.channel_message_id,
        reply_to_id=msg.reply_to_id,
        unread=msg.unread,
        created_at=msg.created_at,
        timestamp=format_relative_time(msg.created_at),
        metadata=msg.metadata,
    )


# ============================================================================
# Channel Management Endpoints
# ============================================================================


@router.get("", response_model=ChannelListResponse)
async def list_channels(request: Request) -> ChannelListResponse:
    """List all registered channels and their status."""
    registry = get_channel_registry(request)

    channels = []
    status = {}

    if registry:
        for name in registry.list_channels():
            provider = registry.get(name)
            channel_status = registry.status.get(name)

            if provider:
                channels.append(
                    ChannelInfo(
                        name=provider.name,
                        display_name=provider.display_name,
                        enabled=True,
                        running=channel_status.running if channel_status else False,
                        healthy=channel_status.healthy if channel_status else False,
                    )
                )

            if channel_status:
                status[name] = ChannelStatusResponse(**channel_status.to_dict())

    return ChannelListResponse(channels=channels, status=status)


@router.get("/{channel}/health", response_model=ChannelHealthResponse)
async def check_channel_health(request: Request, channel: str) -> ChannelHealthResponse:
    """Check health of a specific channel."""
    registry = get_channel_registry(request)

    if not registry:
        return ChannelHealthResponse(channel=channel, healthy=False, error="No channel registry")

    provider = registry.get(channel)
    if not provider:
        return ChannelHealthResponse(channel=channel, healthy=False, error="Channel not found")

    try:
        healthy = await provider.check_health()
        return ChannelHealthResponse(channel=channel, healthy=healthy)
    except Exception as e:
        return ChannelHealthResponse(channel=channel, healthy=False, error=str(e))


@router.post("/{channel}/start")
async def start_channel(
    request: Request, channel: str, current_user: User = Depends(get_current_user)
) -> dict[str, Any]:
    """Start a channel monitor."""
    registry = get_channel_registry(request)

    if not registry:
        raise HTTPException(status_code=503, detail="Channel registry not available")

    provider = registry.get(channel)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Channel not found: {channel}")

    try:
        await registry.start_channel(channel)
        return {"status": "started", "channel": channel}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{channel}/stop")
async def stop_channel(
    request: Request, channel: str, current_user: User = Depends(get_current_user)
) -> dict[str, Any]:
    """Stop a channel monitor."""
    registry = get_channel_registry(request)

    if not registry:
        raise HTTPException(status_code=503, detail="Channel registry not available")

    try:
        await registry.stop_channel(channel)
        return {"status": "stopped", "channel": channel}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Inbox Endpoints
# ============================================================================


@router.get("/inbox", response_model=InboxListResponse)
async def list_inbox_messages(
    request: Request,
    channel: str | None = Query(None, description="Filter by channel"),
    unread: bool | None = Query(None, description="Filter by unread status"),
    limit: int = Query(50, ge=1, le=100, description="Max messages to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> InboxListResponse:
    """List inbox messages with optional filtering."""
    session_manager = get_session_manager(request)

    messages = await session_manager.get_inbox_messages(
        channel=channel,
        unread=unread,
        limit=limit,
        offset=offset,
    )

    unread_count = await session_manager.count_unread(channel=channel)

    return InboxListResponse(
        messages=[inbox_message_to_response(m) for m in messages],
        total=len(messages),
        unread_count=unread_count,
    )


@router.get("/inbox/{message_id}", response_model=InboxMessageResponse)
async def get_inbox_message(request: Request, message_id: str) -> InboxMessageResponse:
    """Get a specific inbox message."""
    storage = get_storage(request)

    try:
        msg_uuid = UUID(message_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid message ID")

    msg = await storage.get_inbox_message(msg_uuid)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    return inbox_message_to_response(msg)


@router.post("/inbox/{message_id}/read")
async def mark_message_read(request: Request, message_id: str) -> dict[str, Any]:
    """Mark a message as read."""
    session_manager = get_session_manager(request)

    try:
        msg_uuid = UUID(message_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid message ID")

    count = await session_manager.mark_messages_read(message_ids=[msg_uuid])
    return {"marked_read": count}


@router.post("/inbox/read")
async def mark_messages_read(
    request: Request,
    session_id: str | None = Query(None, description="Mark all messages in session"),
) -> dict[str, Any]:
    """Mark multiple messages as read."""
    session_manager = get_session_manager(request)

    session_uuid = UUID(session_id) if session_id else None
    count = await session_manager.mark_messages_read(session_id=session_uuid)
    return {"marked_read": count}


@router.post("/inbox/reply", response_model=InboxReplyResponse)
async def reply_to_session(
    request: Request,
    reply_request: InboxReplyRequest,
    current_user: User = Depends(get_current_user),
) -> InboxReplyResponse:
    """Send a reply to a session."""
    message_router = get_message_router(request)

    if not message_router:
        return InboxReplyResponse(
            success=False, error="Message router not available"
        )

    try:
        session_uuid = UUID(reply_request.session_id)
    except ValueError:
        return InboxReplyResponse(
            success=False, error="Invalid session ID"
        )

    result = await message_router.send_message(
        session_id=session_uuid,
        content=reply_request.content,
    )

    return InboxReplyResponse(
        success=result.success,
        message_id=result.message_id,
        error=result.error,
    )


# ============================================================================
# Sessions Endpoints
# ============================================================================


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    request: Request,
    channel: str | None = Query(None, description="Filter by channel"),
    active: bool | None = Query(None, description="Filter by active status"),
    limit: int = Query(50, ge=1, le=100, description="Max sessions to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> SessionListResponse:
    """List sessions with optional filtering."""
    session_manager = get_session_manager(request)

    sessions = await session_manager.list_sessions(
        channel=channel,
        active=active,
        limit=limit,
        offset=offset,
    )

    # Get last message for each session
    session_responses = []
    active_count = 0
    for session in sessions:
        last_msg = await session_manager.get_last_message_content(session.id)
        session_responses.append(session_to_response(session, last_msg))
        if session.active:
            active_count += 1

    return SessionListResponse(
        sessions=session_responses,
        total=len(sessions),
        active_count=active_count,
    )


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session(request: Request, session_id: str) -> SessionDetailResponse:
    """Get a session with its recent messages."""
    session_manager = get_session_manager(request)

    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID")

    session = await session_manager.get_session(session_uuid)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = await session_manager.get_inbox_messages(
        session_id=session_uuid, limit=50
    )

    last_msg = messages[0].content if messages else None

    return SessionDetailResponse(
        session=session_to_response(session, last_msg),
        messages=[inbox_message_to_response(m) for m in messages],
    )


@router.delete("/sessions/{session_id}")
async def delete_session(request: Request, session_id: str) -> dict[str, Any]:
    """Delete (archive) a session."""
    session_manager = get_session_manager(request)

    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID")

    # Just deactivate, don't fully delete
    session = await session_manager.deactivate_session(session_uuid)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"status": "archived", "session_id": session_id}


# ============================================================================
# Real-time Events (SSE)
# ============================================================================


_SSE_TIMEOUT_SECONDS = 300  # 5 minutes


@router.get("/events")
async def channel_events(request: Request):
    """
    Server-Sent Events stream for real-time channel updates.

    Events:
    - new_message: New inbox message received
    - session_update: Session status changed
    - channel_status: Channel status changed
    """
    import asyncio

    async def generate():
        # Send initial connection event
        yield f"event: connected\ndata: {json.dumps({'status': 'connected'})}\n\n"

        elapsed = 0
        interval = 30
        while elapsed < _SSE_TIMEOUT_SECONDS:
            # Check for client disconnect
            if await request.is_disconnected():
                return
            await asyncio.sleep(interval)
            elapsed += interval
            yield f"event: heartbeat\ndata: {json.dumps({'status': 'alive'})}\n\n"

        # Timeout -- close the connection
        yield f"event: timeout\ndata: {json.dumps({'status': 'timeout'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
