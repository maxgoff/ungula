"""
Chat API routes for Ungula.

Provides endpoints for agent chat interactions with streaming support.
"""

import json
import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...agents.runner import AgentRunner
from ...auth import get_current_user
from ...llm.base import ProviderError
from ...storage import StorageBackend
from ...storage.base import User

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    """Request body for chat endpoint."""

    content: str = Field(max_length=100_000)
    provider: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=200_000)
    provider_params: dict | None = Field(
        default=None, description="Provider-specific parameters (e.g., thinking, response_format)"
    )
    agent_id: str | None = Field(
        default=None, description="Agent ID for per-agent configuration"
    )


class ChatResponse(BaseModel):
    """Response from non-streaming chat."""

    message_id: str
    content: str
    model: str
    provider: str
    finish_reason: str | None = None


async def verify_conversation_ownership(
    request: Request, conversation_id: UUID, current_user: User
) -> None:
    """Verify that a conversation exists and belongs to the current user."""
    storage: StorageBackend = request.app.state.storage
    conv = await storage.get_conversation(conversation_id)
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


@router.post("/{conversation_id}", response_model=ChatResponse)
async def chat(
    request: Request,
    conversation_id: str,
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    """
    Send a message and get a response (non-streaming).

    The user message is persisted, then the agent processes it
    and returns the assistant response.
    """
    conv_id = UUID(conversation_id)
    await verify_conversation_ownership(request, conv_id, current_user)

    # Use agent factory if agent_id specified, otherwise default runner
    runner: AgentRunner = request.app.state.agent_runner
    factory = getattr(request.app.state, "agent_factory", None)
    if data.agent_id and factory:
        config = request.app.state.config
        runner = factory.get_or_create(data.agent_id, config.agents)

    try:
        response = await runner.run(
            conv_id,
            data.content,
            stream=False,
            provider=data.provider,
            model=data.model,
            temperature=data.temperature,
            max_tokens=data.max_tokens,
            provider_params=data.provider_params,
        )

        return ChatResponse(
            message_id=str(uuid4()),
            content=response.content or "",
            model=response.model,
            provider=response.provider,
            finish_reason=response.finish_reason,
        )

    except ProviderError as e:
        logger.error("Provider error during chat: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM provider error. Check server logs for details.",
        )
    except Exception as e:
        logger.exception("Unexpected error during chat")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post("/{conversation_id}/stream")
async def chat_stream(
    request: Request,
    conversation_id: str,
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """
    Send a message and stream the response (SSE).

    Events:
    - start: {message_id} - Beginning of response
    - chunk: {content} - Partial text content
    - done: {message_id, finish_reason, model, provider} - Response complete
    - error: {code, message, retryable} - Error occurred
    """
    conv_id = UUID(conversation_id)
    await verify_conversation_ownership(request, conv_id, current_user)

    # Use agent factory if agent_id specified, otherwise default runner
    runner: AgentRunner = request.app.state.agent_runner
    factory = getattr(request.app.state, "agent_factory", None)
    if data.agent_id and factory:
        config = request.app.state.config
        runner = factory.get_or_create(data.agent_id, config.agents)

    async def generate():
        message_id = str(uuid4())

        # Emit start event
        yield f"event: start\ndata: {json.dumps({'message_id': message_id})}\n\n"

        try:
            final_model = None
            final_provider = data.provider or "unknown"

            # Await to get the async iterator, then iterate
            stream_iter = await runner.run(
                conv_id,
                data.content,
                stream=True,
                provider=data.provider,
                model=data.model,
                temperature=data.temperature,
                max_tokens=data.max_tokens,
                provider_params=data.provider_params,
            )
            async for chunk in stream_iter:
                # Handle tool calling events
                if chunk.event_type:
                    yield f"event: {chunk.event_type}\ndata: {json.dumps(chunk.event_data)}\n\n"
                    continue

                if chunk.content:
                    yield f"event: chunk\ndata: {json.dumps({'content': chunk.content})}\n\n"

                if chunk.model:
                    final_model = chunk.model

                if chunk.is_done:
                    yield f"event: done\ndata: {json.dumps({'message_id': message_id, 'finish_reason': chunk.finish_reason, 'model': final_model, 'provider': final_provider})}\n\n"

        except ProviderError as e:
            logger.error("Provider error during streaming: %s", e)
            yield f"event: error\ndata: {json.dumps({'code': 'provider_error', 'message': 'LLM provider error', 'retryable': e.retryable})}\n\n"

        except Exception as e:
            logger.exception("Unexpected error during streaming")
            yield f"event: error\ndata: {json.dumps({'code': 'internal_error', 'message': 'Internal server error', 'retryable': False})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
