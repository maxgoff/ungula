"""
Tests for context pruning.

Verifies that prune_tool_results correctly trims large tool results
based on context pressure levels (soft trim and hard clear).
"""

from ungula.agents.context_pruning import PruningConfig, PruningStats, prune_tool_results
from ungula.agents.compaction import CompactionConfig
from ungula.llm.base import Message as LLMMessage, MessageRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_msg(role: str, content: str, **kwargs) -> LLMMessage:
    """Create an LLMMessage for testing."""
    return LLMMessage(role=MessageRole(role), content=content, **kwargs)


def _make_tool_msg(content: str, tool_call_id: str = "tc1", name: str = "test_tool") -> LLMMessage:
    """Create a tool result LLMMessage."""
    return LLMMessage(
        role=MessageRole.TOOL,
        content=content,
        tool_call_id=tool_call_id,
        name=name,
    )


# ---------------------------------------------------------------------------
# PruningConfig
# ---------------------------------------------------------------------------


class TestPruningConfig:
    """Tests for PruningConfig defaults."""

    def test_defaults(self):
        cfg = PruningConfig()
        assert cfg.enabled is True
        assert cfg.soft_trim_ratio == 0.3
        assert cfg.hard_clear_ratio == 0.5
        assert cfg.max_tool_result_chars == 4000
        assert cfg.head_chars == 1500
        assert cfg.tail_chars == 1500
        assert cfg.keep_recent_turns == 3

    def test_disabled(self):
        cfg = PruningConfig(enabled=False)
        assert cfg.enabled is False


# ---------------------------------------------------------------------------
# prune_tool_results — no pruning
# ---------------------------------------------------------------------------


class TestPruneNoAction:
    """Tests where no pruning should occur."""

    def test_disabled_config(self):
        config = PruningConfig(enabled=False)
        messages = [
            _make_msg("system", "system prompt"),
            _make_tool_msg("x" * 10000),
        ]
        stats = prune_tool_results(messages, 100, 1000, config)
        assert stats.soft_trimmed == 0
        assert stats.hard_cleared == 0
        # Content should be unchanged
        assert len(messages[1].content) == 10000

    def test_under_threshold(self):
        """When context fill is below soft_trim_ratio, nothing is pruned."""
        config = PruningConfig(soft_trim_ratio=0.3)
        messages = [
            _make_msg("system", "prompt"),
            _make_msg("user", "hello"),
            _make_tool_msg("small result"),
        ]
        # Very large max_context to keep fill ratio low
        stats = prune_tool_results(messages, 10, 1_000_000, config)
        assert stats.soft_trimmed == 0
        assert stats.hard_cleared == 0

    def test_small_tool_results_not_trimmed(self):
        """Tool results smaller than max_tool_result_chars are not trimmed."""
        config = PruningConfig(max_tool_result_chars=4000)
        messages = [
            _make_msg("system", "prompt"),
            _make_tool_msg("x" * 3000),  # Under 4000 threshold
        ]
        # Force high fill ratio
        stats = prune_tool_results(messages, 500, 1000, config)
        assert stats.soft_trimmed == 0
        assert len(messages[1].content) == 3000

    def test_default_config_when_none(self):
        """Passing config=None uses default config."""
        messages = [_make_msg("user", "hi")]
        stats = prune_tool_results(messages, 10, 1_000_000, None)
        assert stats.soft_trimmed == 0


# ---------------------------------------------------------------------------
# prune_tool_results — soft trim
# ---------------------------------------------------------------------------


class TestPruneSoftTrim:
    """Tests for soft trim behavior (head+tail with ellipsis)."""

    def test_soft_trim_large_tool_result(self):
        """Large tool result is trimmed to head+tail when in soft trim zone."""
        config = PruningConfig(
            soft_trim_ratio=0.1,
            hard_clear_ratio=0.9,
            max_tool_result_chars=100,
            head_chars=50,
            tail_chars=50,
            keep_recent_turns=0,
            min_prunable_chars=0,
        )
        large_content = "A" * 500
        messages = [
            _make_msg("system", "x" * 100),
            _make_tool_msg(large_content, tool_call_id="tc1"),
            _make_msg("user", "question"),
        ]

        stats = prune_tool_results(messages, 200, 1000, config)

        assert stats.soft_trimmed == 1
        assert stats.hard_cleared == 0
        assert stats.chars_saved > 0
        # Result should contain head, ellipsis, and tail
        assert messages[1].content.startswith("A" * 50)
        assert "trimmed" in messages[1].content
        assert messages[1].content.endswith("A" * 50)

    def test_soft_trim_preserves_recent_turns(self):
        """Tool results in recent assistant turns are not trimmed."""
        config = PruningConfig(
            soft_trim_ratio=0.1,
            hard_clear_ratio=0.9,
            max_tool_result_chars=100,
            head_chars=50,
            tail_chars=50,
            keep_recent_turns=1,
            min_prunable_chars=0,
        )

        messages = [
            _make_msg("system", "prompt"),
            _make_tool_msg("B" * 500, tool_call_id="old"),  # Old — should be trimmed
            _make_msg("assistant", "old response"),
            _make_tool_msg("C" * 500, tool_call_id="recent"),  # Recent — should be kept
            _make_msg("assistant", "latest response"),
        ]

        stats = prune_tool_results(messages, 200, 1000, config)

        # Only the old tool result should be trimmed
        assert stats.soft_trimmed == 1
        assert "trimmed" in messages[1].content
        assert len(messages[3].content) == 500  # Recent one untouched

    def test_soft_trim_preserves_tool_call_id(self):
        """Trimmed messages retain their tool_call_id and name."""
        config = PruningConfig(
            soft_trim_ratio=0.1,
            hard_clear_ratio=0.9,
            max_tool_result_chars=100,
            head_chars=30,
            tail_chars=30,
            keep_recent_turns=0,
            min_prunable_chars=0,
        )

        messages = [
            _make_msg("system", "prompt"),
            _make_tool_msg("D" * 500, tool_call_id="tc-abc", name="web_search"),
        ]

        prune_tool_results(messages, 200, 1000, config)

        assert messages[1].tool_call_id == "tc-abc"
        assert messages[1].name == "web_search"


# ---------------------------------------------------------------------------
# prune_tool_results — hard clear
# ---------------------------------------------------------------------------


class TestPruneHardClear:
    """Tests for hard clear behavior (replace with placeholder)."""

    def test_hard_clear_replaces_content(self):
        """When fill exceeds hard_clear_ratio, tool results are replaced."""
        config = PruningConfig(
            soft_trim_ratio=0.1,
            hard_clear_ratio=0.2,
            max_tool_result_chars=100,
            keep_recent_turns=0,
            min_prunable_chars=0,
        )

        messages = [
            _make_msg("system", "x" * 200),
            _make_tool_msg("E" * 500, tool_call_id="tc1"),
        ]

        # Fill ratio will be high
        stats = prune_tool_results(messages, 300, 1000, config)

        assert stats.hard_cleared == 1
        assert stats.soft_trimmed == 0
        assert "cleared" in messages[1].content.lower()
        assert messages[1].tool_call_id == "tc1"

    def test_hard_clear_multiple_results(self):
        """Multiple old tool results are all hard-cleared."""
        config = PruningConfig(
            soft_trim_ratio=0.1,
            hard_clear_ratio=0.2,
            max_tool_result_chars=100,
            keep_recent_turns=0,
            min_prunable_chars=0,
        )

        messages = [
            _make_msg("system", "x" * 200),
            _make_tool_msg("F" * 500, tool_call_id="tc1"),
            _make_tool_msg("G" * 500, tool_call_id="tc2"),
            _make_msg("user", "continue"),
        ]

        stats = prune_tool_results(messages, 300, 1000, config)

        assert stats.hard_cleared == 2
        assert "cleared" in messages[1].content.lower()
        assert "cleared" in messages[2].content.lower()


# ---------------------------------------------------------------------------
# CompactionConfig
# ---------------------------------------------------------------------------


class TestCompactionConfig:
    """Tests for the new CompactionConfig dataclass."""

    def test_defaults(self):
        cfg = CompactionConfig()
        assert cfg.max_context_tokens == 200_000
        assert cfg.max_history_share == 0.5
        assert cfg.reserve_tokens_floor == 20_000
        assert cfg.min_recent_messages == 6
        assert cfg.safety_margin == 1.2
        assert cfg.summary_max_tokens == 2000

    def test_custom_values(self):
        cfg = CompactionConfig(
            max_context_tokens=100_000,
            max_history_share=0.3,
            reserve_tokens_floor=10_000,
        )
        assert cfg.max_context_tokens == 100_000
        assert cfg.max_history_share == 0.3
        assert cfg.reserve_tokens_floor == 10_000


# ---------------------------------------------------------------------------
# Legacy constants backwards compatibility
# ---------------------------------------------------------------------------


class TestLegacyConstants:
    """Verify backwards-compatible module-level constants still exist."""

    def test_legacy_constants_importable(self):
        from ungula.agents.compaction import (
            COMPACTION_THRESHOLD_RATIO,
            DEFAULT_MAX_CONTEXT_TOKENS,
            MIN_RECENT_MESSAGES,
            SAFETY_MARGIN,
            SUMMARY_SYSTEM_PROMPT,
        )

        assert DEFAULT_MAX_CONTEXT_TOKENS == 100_000
        assert 0 < COMPACTION_THRESHOLD_RATIO < 1.0
        assert MIN_RECENT_MESSAGES >= 1
        assert SAFETY_MARGIN >= 1.0
        assert len(SUMMARY_SYSTEM_PROMPT) > 0
