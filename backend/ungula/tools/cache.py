"""
Tool Result Cache.

In-memory LRU cache with TTL for tool execution results.
Avoids redundant tool calls within a conversation turn.
"""

import hashlib
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A cached tool result with expiry."""

    key: str
    result: Any
    expires_at: float
    created_at: float = field(default_factory=time.monotonic)


class ToolResultCache:
    """
    LRU cache with TTL for tool results.

    Key format: tool_name:sha256(sorted_args)[:16]
    """

    def __init__(self, max_entries: int = 1000, default_ttl: int = 300):
        self.max_entries = max_entries
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def make_key(tool_name: str, kwargs: dict[str, Any]) -> str:
        """Build a cache key from tool name and arguments."""
        args_str = json.dumps(kwargs, sort_keys=True, default=str)
        digest = hashlib.sha256(args_str.encode()).hexdigest()[:16]
        return f"{tool_name}:{digest}"

    def get(self, key: str) -> Any | None:
        """Get a cached result, or None if missing/expired."""
        entry = self._cache.get(key)
        if entry is None:
            self._misses += 1
            return None

        # Check TTL
        if time.monotonic() > entry.expires_at:
            del self._cache[key]
            self._misses += 1
            return None

        # Move to end (most recently used)
        self._cache.move_to_end(key)
        self._hits += 1
        return entry.result

    def put(self, key: str, result: Any, ttl: int | None = None) -> None:
        """Store a result in the cache."""
        ttl = ttl if ttl is not None else self.default_ttl
        now = time.monotonic()

        # Remove if already exists (will re-add at end)
        if key in self._cache:
            del self._cache[key]

        # Evict LRU entries if at capacity
        while len(self._cache) >= self.max_entries:
            evicted_key, _ = self._cache.popitem(last=False)
            logger.debug("Cache evicted LRU entry: %s", evicted_key)

        self._cache[key] = CacheEntry(
            key=key,
            result=result,
            expires_at=now + ttl,
            created_at=now,
        )

    def invalidate(self, tool_name: str) -> int:
        """Remove all cached entries for a given tool. Returns count removed."""
        prefix = f"{tool_name}:"
        keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
        for key in keys_to_remove:
            del self._cache[key]
        return len(keys_to_remove)

    def clear(self) -> None:
        """Remove all cached entries."""
        self._cache.clear()

    def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        # Prune expired entries for accurate count
        now = time.monotonic()
        expired = [k for k, v in self._cache.items() if now > v.expires_at]
        for k in expired:
            del self._cache[k]

        total = self._hits + self._misses
        return {
            "entries": len(self._cache),
            "max_entries": self.max_entries,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total > 0 else 0.0,
        }
