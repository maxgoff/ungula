"""
Node client — WebSocket connection to Ungula gateway.

Handles authentication, heartbeat, and command dispatch.
"""

import asyncio
import json
import logging
import os
import platform
from typing import Any

try:
    import websockets
except ImportError:
    websockets = None

from .capabilities import dispatch, get_capabilities

logger = logging.getLogger(__name__)

# Client version
__version__ = "0.2.0"


def _get_platform_metadata() -> dict[str, Any]:
    """Gather rich platform metadata for registration."""
    return {
        "version": __version__,
        "device_family": platform.machine(),
        "os_version": platform.version(),
        "path_env": os.environ.get("PATH", ""),
    }


class NodeClient:
    """WebSocket client that connects to an Ungula gateway as a node."""

    def __init__(
        self,
        gateway_url: str,
        token: str,
        node_platform: str | None = None,
        heartbeat_interval: int = 30,
        reconnect_delay: int = 5,
        max_reconnect_delay: int = 300,
    ):
        self.gateway_url = gateway_url
        self.token = token
        self.platform = node_platform or platform.system().lower()
        self.heartbeat_interval = heartbeat_interval
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self._ws = None
        self._running = False
        self._node_id: str | None = None

    async def connect(self) -> None:
        """Connect to the gateway and run the event loop."""
        if websockets is None:
            raise RuntimeError("websockets package is required: pip install websockets")

        self._running = True
        delay = self.reconnect_delay

        while self._running:
            try:
                url = f"{self.gateway_url}?token={self.token}"
                async with websockets.connect(url) as ws:
                    self._ws = ws
                    delay = self.reconnect_delay  # Reset on successful connect
                    logger.info("Connected to gateway: %s", self.gateway_url)

                    # Wait for auth response
                    auth_response = await ws.recv()
                    auth_msg = json.loads(auth_response)

                    if auth_msg.get("event") == "node.auth.ok":
                        self._node_id = auth_msg.get("data", {}).get("node_id")
                        logger.info("Authenticated as node: %s", self._node_id)
                    else:
                        error = auth_msg.get("data", {}).get("message", "Unknown error")
                        logger.error("Authentication failed: %s", error)
                        self._running = False
                        return

                    # Register capabilities with extended metadata
                    capabilities = get_capabilities()
                    meta = _get_platform_metadata()
                    await ws.send(json.dumps({
                        "event": "node.register_capabilities",
                        "data": {
                            "capabilities": capabilities,
                            "declared_commands": capabilities,
                            **meta,
                        },
                    }))
                    logger.info("Registered capabilities: %s", capabilities)

                    # Run event loop with heartbeat
                    await self._event_loop(ws)

            except websockets.ConnectionClosed:
                logger.warning("Connection closed. Reconnecting in %ds...", delay)
            except ConnectionRefusedError:
                logger.warning("Connection refused. Retrying in %ds...", delay)
            except Exception as e:
                logger.error("Connection error: %s. Retrying in %ds...", e, delay)

            if self._running:
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.max_reconnect_delay)

    async def pair_and_connect(
        self,
        gateway_url: str,
        name: str,
        node_platform: str | None = None,
    ) -> None:
        """Node-initiated pairing: connect without token, request pairing, wait for approval."""
        if websockets is None:
            raise RuntimeError("websockets package is required: pip install websockets")

        plat = node_platform or platform.system().lower()
        capabilities = get_capabilities()
        meta = _get_platform_metadata()

        # Connect without token
        async with websockets.connect(gateway_url) as ws:
            logger.info("Connected to gateway for pairing: %s", gateway_url)

            # Send pair request
            await ws.send(json.dumps({
                "event": "node.pair.request",
                "data": {
                    "name": name,
                    "platform": plat,
                    "capabilities": capabilities,
                    "metadata": meta,
                },
            }))
            logger.info("Sent pairing request as '%s'", name)

            # Wait for approval/rejection
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)
                event = msg.get("event", "")
                data = msg.get("data", {})

                if event == "node.pair.pending":
                    logger.info("Pairing pending — waiting for operator approval...")
                    continue

                elif event == "node.pair.approved":
                    token = data.get("token", "")
                    node_id = data.get("node_id", "")
                    logger.info("Pairing approved! node_id=%s", node_id)
                    # Store token and reconnect normally
                    self.token = token
                    self.gateway_url = gateway_url
                    self.platform = plat
                    self._node_id = node_id
                    break

                elif event == "node.pair.rejected":
                    logger.error("Pairing rejected by operator")
                    return

                elif event == "node.error":
                    logger.error("Error: %s", data.get("message"))
                    return

        # Now connect normally with the received token
        await self.connect()

    async def _event_loop(self, ws) -> None:
        """Main event loop: receive messages and dispatch commands."""
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))

        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON received")
                    continue

                event = msg.get("event", "")
                data = msg.get("data", {})

                if event == "node.invoke":
                    asyncio.create_task(self._handle_invoke(ws, data))
                elif event == "node.error":
                    logger.error("Gateway error: %s", data.get("message"))
                else:
                    logger.debug("Unknown event: %s", event)
        finally:
            heartbeat_task.cancel()

    async def _handle_invoke(self, ws, data: dict[str, Any]) -> None:
        """Handle a command invocation from the gateway."""
        command = data.get("command", "")
        args = data.get("args", {})
        request_id = data.get("request_id", "")

        logger.info("Invoking command: %s (request_id=%s)", command, request_id)

        # Emit exec.started event
        await self._emit_event(ws, "exec.started", {
            "command": command,
            "request_id": request_id,
        })

        result = await dispatch(command, args)

        # Emit exec.finished or exec.denied event
        event_type = "exec.finished" if result.get("success") else "exec.denied"
        await self._emit_event(ws, event_type, {
            "command": command,
            "request_id": request_id,
            "success": result.get("success", False),
        })

        # Send result back
        response = {
            "event": "node.result",
            "data": {
                "request_id": request_id,
                **result,
            },
        }
        await ws.send(json.dumps(response))

    async def _emit_event(self, ws, event_type: str, payload: dict[str, Any]) -> None:
        """Emit a node event to the gateway."""
        try:
            await ws.send(json.dumps({
                "event": "node.event",
                "data": {
                    "event_type": event_type,
                    "payload": payload,
                },
            }))
        except Exception:
            pass  # Best-effort

    async def _heartbeat_loop(self, ws) -> None:
        """Send periodic heartbeats."""
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                await ws.send(json.dumps({"event": "node.heartbeat", "data": {}}))
            except Exception:
                break

    def stop(self) -> None:
        """Signal the client to stop."""
        self._running = False
