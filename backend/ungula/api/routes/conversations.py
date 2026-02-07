"""
Conversation API routes for Ungula.

Provides CRUD endpoints for conversations and messages.
"""

import asyncio
import logging
from typing import Any
from uuid import UUID

from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ...auth import get_current_user
from ...storage import (
    Conversation,
    ConversationCreate,
    Message,
    MessageCreate,
    StorageBackend,
)
from ...storage.base import User

logger = logging.getLogger(__name__)

router = APIRouter()


# Request/Response Models


class CreateConversationRequest(BaseModel):
    """Request to create a conversation."""

    title: str | None = None
    metadata: dict[str, Any] | None = None


class ConversationResponse(BaseModel):
    """Conversation response."""

    id: str
    user_id: str | None
    title: str | None
    created_at: str
    updated_at: str
    message_count: int = 0

    @classmethod
    def from_conversation(cls, conv: Conversation, message_count: int = 0) -> "ConversationResponse":
        """Create from Conversation model."""
        return cls(
            id=str(conv.id),
            user_id=str(conv.user_id) if conv.user_id else None,
            title=conv.title,
            created_at=conv.created_at.isoformat(),
            updated_at=conv.updated_at.isoformat(),
            message_count=message_count,
        )


class ConversationListResponse(BaseModel):
    """List of conversations response."""

    conversations: list[ConversationResponse]
    total: int


class MessageRole(str, Enum):
    """Allowed message roles."""

    user = "user"
    assistant = "assistant"
    system = "system"


class CreateMessageRequest(BaseModel):
    """Request to create a message."""

    role: MessageRole
    content: str = Field(max_length=500_000)
    agent_id: str | None = None
    model: str | None = None
    metadata: dict[str, Any] | None = None


class MessageResponse(BaseModel):
    """Message response."""

    id: str
    conversation_id: str
    role: str
    content: str
    agent_id: str | None
    model: str | None
    created_at: str

    @classmethod
    def from_message(cls, msg: Message) -> "MessageResponse":
        """Create from Message model."""
        return cls(
            id=str(msg.id),
            conversation_id=str(msg.conversation_id),
            role=msg.role,
            content=msg.content,
            agent_id=msg.agent_id,
            model=msg.model,
            created_at=msg.created_at.isoformat(),
        )


class ConversationDetailResponse(BaseModel):
    """Conversation with messages response."""

    id: str
    user_id: str | None
    title: str | None
    created_at: str
    updated_at: str
    messages: list[MessageResponse]


# Conversation Endpoints


@router.post("/", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    request: Request,
    data: CreateConversationRequest,
    current_user: User = Depends(get_current_user),
) -> ConversationResponse:
    """Create a new conversation."""
    storage: StorageBackend = request.app.state.storage

    # Before creating new conversation, save memory from user's most recent conversation
    try:
        existing = await storage.list_conversations(user_id=current_user.id, limit=1)
        if existing:
            prev_conv = existing[0]
            workspace_dir = getattr(request.app.state, "agent_runner", None)
            registry = getattr(request.app.state, "registry", None)
            if workspace_dir:
                from ...hooks.session_memory import save_session_memory
                from ...config import get_workspace_dir

                asyncio.create_task(
                    save_session_memory(
                        storage=storage,
                        conversation_id=prev_conv.id,
                        workspace_dir=get_workspace_dir(),
                        registry=registry,
                    )
                )
    except Exception as e:
        logger.warning("Failed to trigger session memory save: %s", e)

    conv = await storage.create_conversation(
        ConversationCreate(
            title=data.title,
            user_id=current_user.id,
            metadata=data.metadata or {},
        )
    )

    return ConversationResponse.from_conversation(conv)


@router.get("/", response_model=ConversationListResponse)
async def list_conversations(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
) -> ConversationListResponse:
    """List conversations for the authenticated user."""
    storage: StorageBackend = request.app.state.storage

    conversations = await storage.list_conversations(
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )

    # Get message counts in a single batch query (fixes N+1)
    conv_ids = [conv.id for conv in conversations]
    counts = await storage.count_messages_batch(conv_ids) if conv_ids else {}

    result = [
        ConversationResponse.from_conversation(conv, counts.get(conv.id, 0))
        for conv in conversations
    ]

    return ConversationListResponse(
        conversations=result,
        total=len(result),
    )


async def _get_owned_conversation(
    storage: StorageBackend, conversation_id: str, current_user: User
) -> Conversation:
    """Get a conversation and verify ownership."""
    conv = await storage.get_conversation(UUID(conversation_id))
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    if conv.user_id is not None and str(conv.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return conv


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    request: Request,
    conversation_id: str,
    current_user: User = Depends(get_current_user),
) -> ConversationDetailResponse:
    """Get a conversation with all its messages."""
    storage: StorageBackend = request.app.state.storage

    conv = await _get_owned_conversation(storage, conversation_id, current_user)

    messages = await storage.list_messages(conv.id, limit=1000)

    return ConversationDetailResponse(
        id=str(conv.id),
        user_id=str(conv.user_id) if conv.user_id else None,
        title=conv.title,
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
        messages=[MessageResponse.from_message(m) for m in messages],
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    request: Request,
    conversation_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a conversation and all its messages."""
    storage: StorageBackend = request.app.state.storage

    conv = await _get_owned_conversation(storage, conversation_id, current_user)
    await storage.delete_conversation(conv.id)


# Message Endpoints


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_message(
    request: Request,
    conversation_id: str,
    data: CreateMessageRequest,
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    """Add a message to a conversation."""
    storage: StorageBackend = request.app.state.storage

    conv = await _get_owned_conversation(storage, conversation_id, current_user)

    msg = await storage.create_message(
        MessageCreate(
            conversation_id=conv.id,
            role=data.role.value,
            content=data.content,
            agent_id=data.agent_id,
            model=data.model,
            metadata=data.metadata or {},
        )
    )

    return MessageResponse.from_message(msg)


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    request: Request,
    conversation_id: str,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
) -> list[MessageResponse]:
    """List messages in a conversation."""
    storage: StorageBackend = request.app.state.storage

    conv = await _get_owned_conversation(storage, conversation_id, current_user)
    messages = await storage.list_messages(conv.id, limit=limit, offset=offset)

    return [MessageResponse.from_message(m) for m in messages]
