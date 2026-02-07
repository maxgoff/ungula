"""
Slack threading utilities.

Handles thread-aware replies so conversations stay organized
in Slack threads.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ThreadTracker:
    """
    Tracks Slack thread contexts for conversations.

    Maps conversation sessions to their Slack thread timestamps,
    enabling threaded replies within the same conversation context.
    """

    def __init__(self, max_threads: int = 1000):
        self.max_threads = max_threads
        # Maps (channel_id, session_key) -> thread_ts
        self._threads: dict[tuple[str, str], str] = {}

    def get_thread_ts(self, channel_id: str, session_key: str) -> str | None:
        """Get the thread timestamp for a session."""
        return self._threads.get((channel_id, session_key))

    def set_thread_ts(self, channel_id: str, session_key: str, thread_ts: str) -> None:
        """Record a thread timestamp for a session."""
        # Evict oldest if at capacity
        if len(self._threads) >= self.max_threads:
            oldest_key = next(iter(self._threads))
            del self._threads[oldest_key]

        self._threads[(channel_id, session_key)] = thread_ts

    def clear_thread(self, channel_id: str, session_key: str) -> None:
        """Clear a thread mapping."""
        self._threads.pop((channel_id, session_key), None)
