"""
WebSocket route for real-time communication.

Supports JWT authentication via query parameter or first message.
Protocol messages:
  - chat.subscribe  (client -> server): Subscribe to conversation events
  - chat.send       (client -> server): Send a chat message
  - chat.chunk      (server -> client): Streaming response chunk
  - chat.done       (server -> client): Response complete
  - chat.error      (server -> client): Error occurred
  - inbox.new       (server -> client): New inbox message
  - channel.status  (server -> client): Channel status change
  - error           (server -> client): Protocol error
"""

import json
import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ...auth import _resolve_user
from ..ws_manager import ConnectionManager

logger = logging.getLogger(__name__)

router = APIRouter()


async def _authenticate_ws(
    websocket: WebSocket,
    token: str | None,
) -> UUID | None:
    """Authenticate a WebSocket connection via JWT token.

    Returns the user_id if valid, None otherwise.
    """
    if not token:
        return None

    user = await _resolve_user(token)
    if user:
        return user.id
    return None


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(default=None),
):
    """
    Main WebSocket endpoint.

    Authentication: Pass JWT token as ?token= query parameter,
    or send it in the first message as {"event": "auth", "data": {"token": "..."}}.
    """
    manager: ConnectionManager = websocket.app.state.ws_manager
    connection_id = str(uuid4())
    user_id: UUID | None = None

    # Try token from query param
    if token:
        user_id = await _authenticate_ws(websocket, token)

    # Accept connection (even without auth -- they can auth via first message)
    accepted = await manager.connect(connection_id, websocket, user_id=user_id)
    if not accepted:
        await websocket.close(code=1013, reason="Max connections exceeded")
        return

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await manager._send_json(connection_id, {
                    "event": "error",
                    "data": {"message": "Invalid JSON"},
                })
                continue

            event = message.get("event", "")
            data = message.get("data", {})

            if event == "auth":
                # Late authentication
                auth_token = data.get("token")
                new_user_id = await _authenticate_ws(websocket, auth_token)
                if new_user_id:
                    user_id = new_user_id
                    # Update connection's user_id
                    conn = manager._connections.get(connection_id)
                    if conn:
                        conn.user_id = user_id
                        uid_str = str(user_id)
                        if uid_str not in manager._user_connections:
                            manager._user_connections[uid_str] = set()
                        manager._user_connections[uid_str].add(connection_id)
                    await manager._send_json(connection_id, {
                        "event": "auth.ok",
                        "data": {"user_id": str(user_id)},
                    })
                else:
                    await manager._send_json(connection_id, {
                        "event": "auth.error",
                        "data": {"message": "Invalid token"},
                    })

            elif event == "chat.subscribe":
                # Subscribe to a conversation's events
                conv_id_str = data.get("conversation_id")
                if not conv_id_str:
                    await manager._send_json(connection_id, {
                        "event": "error",
                        "data": {"message": "conversation_id required"},
                    })
                    continue
                try:
                    conv_id = UUID(conv_id_str)
                except ValueError:
                    await manager._send_json(connection_id, {
                        "event": "error",
                        "data": {"message": "Invalid conversation_id"},
                    })
                    continue
                await manager.subscribe_conversation(connection_id, conv_id)
                await manager._send_json(connection_id, {
                    "event": "chat.subscribed",
                    "data": {"conversation_id": conv_id_str},
                })

            elif event == "chat.send":
                # Send a chat message through the agent
                if not user_id:
                    await manager._send_json(connection_id, {
                        "event": "error",
                        "data": {"message": "Authentication required"},
                    })
                    continue

                conv_id_str = data.get("conversation_id")
                content = data.get("content", "")

                if not conv_id_str or not content:
                    await manager._send_json(connection_id, {
                        "event": "error",
                        "data": {"message": "conversation_id and content required"},
                    })
                    continue

                try:
                    conv_id = UUID(conv_id_str)
                except ValueError:
                    await manager._send_json(connection_id, {
                        "event": "error",
                        "data": {"message": "Invalid conversation_id"},
                    })
                    continue

                # Process via agent runner (streaming)
                await _handle_chat_send(
                    manager=manager,
                    connection_id=connection_id,
                    conversation_id=conv_id,
                    content=content,
                    websocket=websocket,
                )

            elif event == "ping":
                await manager._send_json(connection_id, {
                    "event": "pong",
                    "data": {},
                })

            else:
                await manager._send_json(connection_id, {
                    "event": "error",
                    "data": {"message": f"Unknown event: {event}"},
                })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected: %s", connection_id)
    except Exception as e:
        logger.error("WebSocket error for %s: %s", connection_id, e, exc_info=True)
    finally:
        await manager.disconnect(connection_id)


async def _handle_chat_send(
    manager: ConnectionManager,
    connection_id: str,
    conversation_id: UUID,
    content: str,
    websocket: WebSocket,
) -> None:
    """Process a chat.send message through the agent runner with streaming."""
    agent_runner = websocket.app.state.agent_runner

    try:
        stream = await agent_runner.run(
            conversation_id=conversation_id,
            user_message=content,
            stream=True,
        )

        async for chunk in stream:
            if chunk.content:
                await manager._send_json(connection_id, {
                    "event": "chat.chunk",
                    "data": {
                        "conversation_id": str(conversation_id),
                        "content": chunk.content,
                        "model": chunk.model,
                    },
                })

            if chunk.event_type == "tool_call":
                await manager._send_json(connection_id, {
                    "event": "chat.tool_call",
                    "data": {
                        "conversation_id": str(conversation_id),
                        **chunk.event_data,
                    },
                })

            if chunk.event_type == "tool_result":
                await manager._send_json(connection_id, {
                    "event": "chat.tool_result",
                    "data": {
                        "conversation_id": str(conversation_id),
                        **chunk.event_data,
                    },
                })

            if chunk.is_done:
                await manager._send_json(connection_id, {
                    "event": "chat.done",
                    "data": {
                        "conversation_id": str(conversation_id),
                        "model": chunk.model,
                        "finish_reason": chunk.finish_reason,
                    },
                })

    except Exception as e:
        logger.error("Chat send error: %s", e, exc_info=True)
        await manager._send_json(connection_id, {
            "event": "chat.error",
            "data": {
                "conversation_id": str(conversation_id),
                "message": "Failed to process message",
            },
        })
