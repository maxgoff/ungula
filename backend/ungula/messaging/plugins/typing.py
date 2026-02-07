"""
Typing indicator management for channels.

Shows typing indicators while the agent is processing a message,
giving users visual feedback that a response is being generated.
"""

import asyncio
import logging
from typing import Any

from ..base import ChannelProvider

logger = logging.getLogger(__name__)


class TypingManager:
    """
    Manages typing indicators across channels.

    Sends periodic typing indicators while the agent is processing,
    then stops when the response is ready.
    """

    def __init__(self, interval: float = 3.0):
        """
        Args:
            interval: Seconds between typing indicator refreshes.
        """
        self.interval = interval
        self._active_tasks: dict[str, asyncio.Task] = {}

    async def start_typing(
        self,
        provider: ChannelProvider,
        target: str,
        session_key: str,
    ) -> None:
        """
        Start showing typing indicator.

        Args:
            provider: The channel provider to send typing to.
            target: Channel-specific target (channel ID, etc.).
            session_key: Unique key for this typing session.
        """
        # Cancel any existing typing for this session
        await self.stop_typing(session_key)

        task = asyncio.create_task(
            self._typing_loop(provider, target, session_key)
        )
        self._active_tasks[session_key] = task

    async def stop_typing(self, session_key: str) -> None:
        """Stop showing typing indicator for a session."""
        task = self._active_tasks.pop(session_key, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _typing_loop(
        self,
        provider: ChannelProvider,
        target: str,
        session_key: str,
    ) -> None:
        """Send periodic typing indicators."""
        try:
            while True:
                try:
                    # Call typing_start if the provider supports it
                    if hasattr(provider, "typing_start"):
                        await provider.typing_start(target)
                except Exception as e:
                    logger.debug("Typing indicator failed: %s", e)
                await asyncio.sleep(self.interval)
        except asyncio.CancelledError:
            pass
