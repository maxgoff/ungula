"""
File watcher for auto-indexing workspace files into memory.

Uses watchdog to monitor a directory for changes and re-indexes
modified files into the vector memory system.
"""

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .manager import MemoryManager

logger = logging.getLogger(__name__)

# File extensions to watch
WATCHED_EXTENSIONS = {".md", ".txt", ".py", ".yaml", ".yml", ".json", ".toml"}
# Directories to skip
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv"}


class FileWatcher:
    """
    Watches a directory for file changes and auto-indexes into memory.

    Uses watchdog for filesystem events and debounces rapid changes.
    """

    def __init__(
        self,
        watch_dir: Path,
        memory_manager: "MemoryManager",
        debounce_seconds: float = 2.0,
    ):
        self.watch_dir = watch_dir
        self.memory_manager = memory_manager
        self.debounce_seconds = debounce_seconds
        self._observer = None
        self._pending: dict[str, asyncio.TimerHandle] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False

    async def start(self) -> None:
        """Start watching for file changes."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            logger.warning("watchdog not installed, file watching disabled")
            return

        if not self.watch_dir.exists():
            logger.warning("Watch directory does not exist: %s", self.watch_dir)
            return

        self._loop = asyncio.get_event_loop()
        self._running = True

        class Handler(FileSystemEventHandler):
            def __init__(self, watcher: "FileWatcher"):
                self.watcher = watcher

            def on_modified(self, event):
                if not event.is_directory:
                    self.watcher._schedule_reindex(event.src_path)

            def on_created(self, event):
                if not event.is_directory:
                    self.watcher._schedule_reindex(event.src_path)

        handler = Handler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.watch_dir), recursive=True)
        self._observer.daemon = True
        self._observer.start()

        logger.info("File watcher started for %s", self.watch_dir)

    async def stop(self) -> None:
        """Stop watching."""
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        logger.info("File watcher stopped")

    def _schedule_reindex(self, file_path: str) -> None:
        """Schedule a debounced re-index for a file."""
        if not self._running or not self._loop:
            return

        path = Path(file_path)

        # Check if this file should be watched
        if not self._should_watch(path):
            return

        # Cancel any pending reindex for this file
        if file_path in self._pending:
            self._pending[file_path].cancel()

        # Schedule new reindex after debounce period
        handle = self._loop.call_later(
            self.debounce_seconds,
            lambda p=file_path: asyncio.ensure_future(self._reindex_file(p)),
        )
        self._pending[file_path] = handle

    def _should_watch(self, path: Path) -> bool:
        """Check if a file should be watched."""
        # Check extension
        if path.suffix not in WATCHED_EXTENSIONS:
            return False
        # Check skip dirs
        for part in path.parts:
            if part in SKIP_DIRS:
                return False
        return True

    async def _reindex_file(self, file_path: str) -> None:
        """Re-index a single file into memory."""
        self._pending.pop(file_path, None)
        path = Path(file_path)

        if not path.exists():
            logger.debug("File no longer exists, skipping: %s", file_path)
            return

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            if not content.strip():
                return

            # Use relative path as source
            try:
                source = str(path.relative_to(self.watch_dir))
            except ValueError:
                source = str(path)

            chunks = await self.memory_manager.index_document(
                content=content,
                source=source,
                memory_type="fact",
                level="project",
            )
            logger.info("Re-indexed %s: %d chunks", source, chunks)

        except Exception as e:
            logger.error("Failed to reindex %s: %s", file_path, e)

    async def index_directory(self) -> int:
        """
        Index all watched files in the directory.

        Useful for initial indexing on startup.

        Returns:
            Total number of chunks indexed.
        """
        total_chunks = 0

        for path in self.watch_dir.rglob("*"):
            if path.is_file() and self._should_watch(path):
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                    if not content.strip():
                        continue

                    try:
                        source = str(path.relative_to(self.watch_dir))
                    except ValueError:
                        source = str(path)

                    chunks = await self.memory_manager.index_document(
                        content=content,
                        source=source,
                        memory_type="fact",
                        level="project",
                    )
                    total_chunks += chunks
                except Exception as e:
                    logger.warning("Failed to index %s: %s", path, e)

        logger.info(
            "Initial indexing complete: %d total chunks from %s",
            total_chunks,
            self.watch_dir,
        )
        return total_chunks
