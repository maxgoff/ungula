"""
Tests for tool result caching.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from ungula.tools.base import Tool, ToolParameter, ToolResult, ToolRegistry
from ungula.tools.cache import ToolResultCache


# --- ToolResultCache unit tests ---


class TestToolResultCache:
    """Tests for ToolResultCache."""

    def test_make_key(self):
        """Key format: tool_name:sha256(sorted_args)[:16]."""
        key = ToolResultCache.make_key("web_search", {"query": "test"})
        assert key.startswith("web_search:")
        assert len(key.split(":")[1]) == 16

    def test_make_key_deterministic(self):
        """Same args produce same key regardless of dict order."""
        k1 = ToolResultCache.make_key("t", {"a": 1, "b": 2})
        k2 = ToolResultCache.make_key("t", {"b": 2, "a": 1})
        assert k1 == k2

    def test_put_and_get(self):
        cache = ToolResultCache()
        result = ToolResult(success=True, output="hello")
        cache.put("k1", result)
        assert cache.get("k1") is result

    def test_get_missing(self):
        cache = ToolResultCache()
        assert cache.get("nope") is None

    def test_ttl_expiry(self):
        cache = ToolResultCache(default_ttl=1)
        cache.put("k1", "val", ttl=0)  # 0-second TTL = immediate expiry
        # monotonic time will have advanced
        assert cache.get("k1") is None

    def test_lru_eviction(self):
        cache = ToolResultCache(max_entries=3)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        # Access 'a' to make it recently used
        cache.get("a")
        # Adding 'd' should evict 'b' (least recently used)
        cache.put("d", 4)
        assert cache.get("b") is None
        assert cache.get("a") == 1
        assert cache.get("d") == 4

    def test_invalidate(self):
        cache = ToolResultCache()
        cache.put("web_search:abc", 1)
        cache.put("web_search:def", 2)
        cache.put("shell:ghi", 3)
        removed = cache.invalidate("web_search")
        assert removed == 2
        assert cache.get("web_search:abc") is None
        assert cache.get("shell:ghi") == 3

    def test_clear(self):
        cache = ToolResultCache()
        cache.put("a", 1)
        cache.put("b", 2)
        cache.clear()
        assert cache.get("a") is None

    def test_stats(self):
        cache = ToolResultCache()
        cache.put("k1", "v1")
        cache.get("k1")  # hit
        cache.get("k1")  # hit
        cache.get("miss")  # miss

        stats = cache.stats()
        assert stats["entries"] == 1
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] == pytest.approx(2 / 3, abs=0.01)

    def test_stats_prunes_expired(self):
        cache = ToolResultCache()
        cache.put("k1", "v1", ttl=0)
        stats = cache.stats()
        assert stats["entries"] == 0


# --- ToolRegistry caching integration ---


class DummyTool(Tool):
    """A simple tool for testing."""

    name = "dummy"
    description = "Test tool"
    parameters = []
    cacheable = True
    cache_ttl = 60

    def __init__(self):
        self.call_count = 0

    async def execute(self, **kwargs):
        self.call_count += 1
        return ToolResult(success=True, output=f"result-{self.call_count}")


class NonCacheableTool(Tool):
    """A tool that should not be cached."""

    name = "no_cache"
    description = "Not cached"
    parameters = []
    cacheable = False

    def __init__(self):
        self.call_count = 0

    async def execute(self, **kwargs):
        self.call_count += 1
        return ToolResult(success=True, output=f"result-{self.call_count}")


@pytest.mark.asyncio
async def test_registry_cache_hit():
    """Second call with same args should be a cache hit."""
    cache = ToolResultCache()
    registry = ToolRegistry(cache=cache)
    tool = DummyTool()
    registry.register(tool)

    r1 = await registry.execute("dummy", query="test")
    r2 = await registry.execute("dummy", query="test")

    assert r1.output == "result-1"
    assert r2.output == "result-1"  # Same output = cache hit
    assert tool.call_count == 1


@pytest.mark.asyncio
async def test_registry_cache_different_args():
    """Different args should not hit cache."""
    cache = ToolResultCache()
    registry = ToolRegistry(cache=cache)
    tool = DummyTool()
    registry.register(tool)

    r1 = await registry.execute("dummy", query="test1")
    r2 = await registry.execute("dummy", query="test2")

    assert r1.output == "result-1"
    assert r2.output == "result-2"
    assert tool.call_count == 2


@pytest.mark.asyncio
async def test_registry_no_cache_for_non_cacheable():
    """Non-cacheable tools should always execute."""
    cache = ToolResultCache()
    registry = ToolRegistry(cache=cache)
    tool = NonCacheableTool()
    registry.register(tool)

    r1 = await registry.execute("no_cache", x=1)
    r2 = await registry.execute("no_cache", x=1)

    assert tool.call_count == 2


@pytest.mark.asyncio
async def test_registry_no_cache_when_none():
    """Registry with no cache should work normally."""
    registry = ToolRegistry(cache=None)
    tool = DummyTool()
    registry.register(tool)

    r1 = await registry.execute("dummy", query="test")
    r2 = await registry.execute("dummy", query="test")

    assert tool.call_count == 2
