"""
Signal CLI daemon management.

Manages the signal-cli subprocess for sending and receiving
Signal messages via JSON-RPC.
"""

import asyncio
import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class SignalDaemon:
    """
    Manages a signal-cli JSON-RPC subprocess.

    signal-cli can run in daemon mode, accepting JSON-RPC commands
    via stdin/stdout for sending messages and reporting received ones.
    """

    def __init__(
        self,
        cli_path: str = "signal-cli",
        account: str | None = None,
    ):
        self.cli_path = cli_path
        self.account = account
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._on_message: Callable | None = None
        self._rpc_id = 0

    async def start(self, on_message: Callable | None = None) -> None:
        """
        Start the signal-cli daemon in JSON-RPC mode.

        Args:
            on_message: Callback for received messages.
        """
        self._on_message = on_message

        cmd = [self.cli_path, "--output=json"]
        if self.account:
            cmd.extend(["-a", self.account])
        cmd.append("jsonRpc")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            logger.info("signal-cli daemon started (pid=%d)", self._process.pid)

            # Start reading stdout for incoming messages
            self._reader_task = asyncio.create_task(self._read_loop())

        except FileNotFoundError:
            raise RuntimeError(
                f"signal-cli not found at '{self.cli_path}'. "
                "Install from https://github.com/AsamK/signal-cli"
            )

    async def stop(self) -> None:
        """Stop the signal-cli daemon."""
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None

        logger.info("signal-cli daemon stopped")

    async def send_message(self, recipient: str, message: str) -> bool:
        """
        Send a message via signal-cli JSON-RPC.

        Args:
            recipient: Phone number (e.g., +1234567890).
            message: Message text.

        Returns:
            True if sent successfully.
        """
        if not self._process or not self._process.stdin:
            logger.error("signal-cli not running")
            return False

        self._rpc_id += 1
        rpc_request = {
            "jsonrpc": "2.0",
            "method": "send",
            "id": self._rpc_id,
            "params": {
                "recipient": [recipient],
                "message": message,
            },
        }

        try:
            line = json.dumps(rpc_request) + "\n"
            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()
            return True
        except Exception as e:
            logger.error("Failed to send via signal-cli: %s", e)
            return False

    async def send_group_message(
        self, group_id: str, message: str
    ) -> bool:
        """Send a message to a Signal group."""
        if not self._process or not self._process.stdin:
            return False

        self._rpc_id += 1
        rpc_request = {
            "jsonrpc": "2.0",
            "method": "send",
            "id": self._rpc_id,
            "params": {
                "groupId": group_id,
                "message": message,
            },
        }

        try:
            line = json.dumps(rpc_request) + "\n"
            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()
            return True
        except Exception as e:
            logger.error("Failed to send group message via signal-cli: %s", e)
            return False

    async def _read_loop(self) -> None:
        """Read JSON-RPC notifications from signal-cli stdout."""
        if not self._process or not self._process.stdout:
            return

        while True:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    logger.warning("signal-cli stdout closed")
                    break

                data = json.loads(line.decode().strip())

                # Handle incoming message notifications
                if "method" in data and data["method"] == "receive":
                    params = data.get("params", {})
                    envelope = params.get("envelope", {})
                    await self._handle_envelope(envelope)

            except json.JSONDecodeError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("signal-cli read error: %s", e)

    async def _handle_envelope(self, envelope: dict) -> None:
        """Process a received Signal envelope."""
        if self._on_message is None:
            return

        data_message = envelope.get("dataMessage")
        if not data_message:
            return

        text = data_message.get("message", "")
        if not text:
            return

        source = envelope.get("source", "unknown")
        timestamp = envelope.get("timestamp", 0)
        group_info = data_message.get("groupInfo")

        message_data = {
            "sender": source,
            "text": text,
            "timestamp": timestamp,
            "group_id": group_info.get("groupId") if group_info else None,
            "group_name": group_info.get("name") if group_info else None,
        }

        try:
            await self._on_message(message_data)
        except Exception as e:
            logger.error("Error processing Signal message: %s", e)
