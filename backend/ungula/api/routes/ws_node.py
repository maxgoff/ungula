"""
WebSocket endpoint for companion device (node) connections.

Nodes connect via /ws/node and authenticate with their pairing token.
Protocol follows the node message format defined in nodes/protocol.py.
"""

import json
import logging
from uuid import uuid4

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ...nodes.protocol import (
    NodeEvent,
    NodeMessage,
    auth_ok_message,
    auth_error_message,
    error_message,
    pair_pending_message,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _extract_metadata(data: dict) -> dict:
    """Extract extended metadata fields from a message data dict."""
    return {
        k: data[k]
        for k in ("declared_commands", "device_family", "version", "os_version", "path_env", "metadata")
        if k in data
    }


@router.websocket("/ws/node")
async def node_websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(default=None),
):
    """
    WebSocket endpoint for companion device nodes.

    Authentication: Node sends token via query param or first message.
    After auth, node sends heartbeats and receives invoke commands.
    Unauthenticated nodes can send PAIR_REQUEST for node-initiated pairing.
    """
    node_manager = websocket.app.state.node_manager
    node_registry = node_manager.registry
    authenticated_node_id: str | None = None

    await websocket.accept()

    try:
        # Authentication phase
        if token:
            node_model = await node_manager.authenticate_node(token)
            if node_model:
                authenticated_node_id = node_model.id
                node_registry.register(
                    node_id=node_model.id,
                    name=node_model.name,
                    platform=node_model.platform,
                    capabilities=node_model.capabilities or [],
                    websocket=websocket,
                )
                await websocket.send_json(
                    auth_ok_message(node_model.id).to_dict()
                )
                logger.info("Node authenticated via query: %s (%s)", node_model.name, node_model.id)
            else:
                await websocket.send_json(
                    auth_error_message("Invalid token").to_dict()
                )
                await websocket.close(code=4001, reason="Invalid token")
                return

        # Message loop
        while True:
            raw = await websocket.receive_text()

            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(
                    error_message("Invalid JSON").to_dict()
                )
                continue

            event = message.get("event", "")
            data = message.get("data", {})

            if event == NodeEvent.AUTH:
                # Late authentication
                auth_token = data.get("token", "")
                node_model = await node_manager.authenticate_node(auth_token)
                if node_model:
                    authenticated_node_id = node_model.id
                    capabilities = data.get("capabilities", node_model.capabilities or [])
                    platform = data.get("platform", node_model.platform)
                    meta = _extract_metadata(data)
                    node_registry.register(
                        node_id=node_model.id,
                        name=node_model.name,
                        platform=platform,
                        capabilities=capabilities,
                        websocket=websocket,
                        **meta,
                    )
                    await websocket.send_json(
                        auth_ok_message(node_model.id).to_dict()
                    )
                    logger.info("Node authenticated: %s (%s)", node_model.name, node_model.id)
                else:
                    await websocket.send_json(
                        auth_error_message("Invalid token").to_dict()
                    )

            elif event == NodeEvent.PAIR_REQUEST:
                # Node-initiated pairing (WI 2)
                if authenticated_node_id:
                    await websocket.send_json(
                        error_message("Already authenticated").to_dict()
                    )
                    continue

                name = data.get("name", "Unknown Node")
                platform = data.get("platform", "unknown")
                capabilities = data.get("capabilities", [])
                metadata = data.get("metadata")

                result = await node_manager.node_initiated_pairing(
                    name=name,
                    platform=platform,
                    capabilities=capabilities,
                    metadata=metadata,
                    websocket=websocket,
                )
                # Tell node to wait for approval
                await websocket.send_json(
                    pair_pending_message(result["node_id"]).to_dict()
                )
                logger.info(
                    "Node-initiated pairing request: %s (%s)",
                    name, result["node_id"],
                )
                # Node stays connected, waiting for pair_approved/pair_rejected
                # which will be sent by approve_pairing/reject_pairing in manager

            elif event == NodeEvent.REGISTER_CAPABILITIES:
                if not authenticated_node_id:
                    await websocket.send_json(
                        error_message("Not authenticated").to_dict()
                    )
                    continue
                # Update capabilities and metadata
                new_caps = data.get("capabilities", [])
                node = node_registry.get(authenticated_node_id)
                if node:
                    node.capabilities = new_caps
                    # Update extended metadata if provided
                    meta = _extract_metadata(data)
                    if "declared_commands" in meta:
                        node.declared_commands = meta["declared_commands"]
                    if "device_family" in meta:
                        node.device_family = meta["device_family"]
                    if "version" in meta:
                        node.version = meta["version"]
                    if "os_version" in meta:
                        node.os_version = meta["os_version"]
                    if "path_env" in meta:
                        node.path_env = meta["path_env"]
                    if "metadata" in meta:
                        node.metadata.update(meta["metadata"])
                    logger.info("Node %s updated capabilities: %s", authenticated_node_id, new_caps)

            elif event == NodeEvent.HEARTBEAT:
                if authenticated_node_id:
                    node_registry.update_heartbeat(authenticated_node_id)

            elif event == NodeEvent.RESULT:
                # Node is reporting result of a command invocation
                request_id = data.get("request_id", "")
                if request_id:
                    node_manager.handle_result(request_id, data)

            elif event == NodeEvent.NODE_EVENT:
                # Node event reporting (WI 6)
                if not authenticated_node_id:
                    continue
                event_type = data.get("event_type", "unknown")
                payload = data.get("payload", {})
                logger.info(
                    "Node event from %s: %s %s",
                    authenticated_node_id, event_type, json.dumps(payload)[:200],
                )
                # Broadcast to dashboard WebSocket manager if available
                ws_manager = getattr(websocket.app.state, "ws_manager", None)
                if ws_manager:
                    await ws_manager.broadcast({
                        "type": "node_event",
                        "node_id": authenticated_node_id,
                        "event_type": event_type,
                        "payload": payload,
                    })

            else:
                await websocket.send_json(
                    error_message(f"Unknown event: {event}").to_dict()
                )

    except WebSocketDisconnect:
        logger.info("Node disconnected: %s", authenticated_node_id or "unauthenticated")
    except Exception as e:
        logger.error("Node WebSocket error: %s", e, exc_info=True)
    finally:
        if authenticated_node_id:
            await node_manager.on_node_disconnect(authenticated_node_id)
