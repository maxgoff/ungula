"""
iMessage database monitor.

Polls ~/Library/Messages/chat.db for new messages using SQLite read-only access.
"""

import asyncio
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# iMessage stores timestamps as seconds since 2001-01-01
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)

# Query for recent messages
RECENT_MESSAGES_QUERY = """
SELECT
    m.ROWID,
    m.text,
    m.date,
    m.is_from_me,
    h.id as handle_id,
    COALESCE(h.uncanonicalized_id, h.id) as sender
FROM message m
LEFT JOIN handle h ON m.handle_id = h.ROWID
WHERE m.date > ?
    AND m.text IS NOT NULL
    AND m.text != ''
    AND m.is_from_me = 0
ORDER BY m.date ASC
LIMIT 50
"""


def apple_timestamp_to_datetime(ts: int) -> datetime:
    """Convert Apple timestamp (nanoseconds since 2001-01-01) to datetime."""
    if ts > 1e15:
        # Nanoseconds (newer macOS versions)
        seconds = ts / 1e9
    else:
        # Seconds (older macOS versions)
        seconds = ts
    return datetime.fromtimestamp(APPLE_EPOCH.timestamp() + seconds, tz=UTC)


class IMessageMonitor:
    """
    Monitors the iMessage database for new messages.

    Uses read-only SQLite access to poll for new messages
    at a configurable interval.
    """

    def __init__(
        self,
        db_path: Path,
        on_message: Callable,
        poll_interval: float = 2.0,
    ):
        self.db_path = db_path
        self.on_message = on_message
        self.poll_interval = poll_interval
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_date: int = 0

    async def start(self) -> None:
        """Start polling for new messages."""
        if self._running:
            return

        # Initialize last_date to current time to avoid processing old messages
        self._last_date = self._get_current_apple_timestamp()
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("iMessage monitor started (polling every %.1fs)", self.poll_interval)

    async def stop(self) -> None:
        """Stop polling."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("iMessage monitor stopped")

    def _get_current_apple_timestamp(self) -> int:
        """Get current time as Apple nanosecond timestamp."""
        now = datetime.now(UTC)
        delta = now.timestamp() - APPLE_EPOCH.timestamp()
        return int(delta * 1e9)

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await self._check_new_messages()
            except Exception as e:
                logger.error("iMessage poll error: %s", e)
            await asyncio.sleep(self.poll_interval)

    async def _check_new_messages(self) -> None:
        """Check for new messages since last poll."""
        try:
            # Read-only connection
            conn = sqlite3.connect(
                f"file:{self.db_path}?mode=ro",
                uri=True,
                timeout=5,
            )
            conn.row_factory = sqlite3.Row

            cursor = conn.execute(RECENT_MESSAGES_QUERY, (self._last_date,))
            rows = cursor.fetchall()
            conn.close()

            for row in rows:
                self._last_date = max(self._last_date, row["date"])

                message_data = {
                    "rowid": row["ROWID"],
                    "text": row["text"],
                    "date": row["date"],
                    "sender": row["sender"] or row["handle_id"] or "unknown",
                    "timestamp": apple_timestamp_to_datetime(row["date"]),
                }

                try:
                    await self.on_message(message_data)
                except Exception as e:
                    logger.error("Error processing iMessage: %s", e)

        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                logger.debug("iMessage DB locked, will retry")
            else:
                raise
