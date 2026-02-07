"""
Tests for the messaging plugins: typing, reactions, command_gating, mention_gating.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ungula.messaging.plugins.command_gating import CommandGate, DEFAULT_PERMISSIONS
from ungula.messaging.plugins.mention_gating import MentionGate
from ungula.messaging.plugins.reactions import (
    ACK_REACTION,
    DONE_REACTION,
    ERROR_REACTION,
    ReactionManager,
)
from ungula.messaging.plugins.typing import TypingManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_provider(*, has_typing: bool = True, has_react: bool = True):
    """
    Create a mock ChannelProvider with optional typing_start and react methods.

    Args:
        has_typing: Whether the mock should have a typing_start method.
        has_react: Whether the mock should have a react method.

    Returns:
        A MagicMock that mimics ChannelProvider.
    """
    provider = MagicMock()
    if has_typing:
        provider.typing_start = AsyncMock()
    else:
        # Remove the attr so hasattr() returns False
        del provider.typing_start

    if has_react:
        provider.react = AsyncMock()
    else:
        del provider.react

    return provider


# ===========================================================================
# TypingManager tests
# ===========================================================================

class TestTypingManager:
    """Tests for TypingManager."""

    async def test_start_typing_calls_provider(self):
        """start_typing should call provider.typing_start at least once."""
        provider = _make_mock_provider()
        manager = TypingManager(interval=0.05)

        await manager.start_typing(provider, "channel-123", "session-1")

        # Let the typing loop run at least one iteration
        await asyncio.sleep(0.1)
        await manager.stop_typing("session-1")

        provider.typing_start.assert_called_with("channel-123")
        assert provider.typing_start.call_count >= 1

    async def test_stop_typing_cancels_task(self):
        """stop_typing should cancel the background typing task."""
        provider = _make_mock_provider()
        manager = TypingManager(interval=0.05)

        await manager.start_typing(provider, "channel-123", "session-1")
        assert "session-1" in manager._active_tasks

        await manager.stop_typing("session-1")
        assert "session-1" not in manager._active_tasks

    async def test_stop_typing_nonexistent_session(self):
        """stop_typing on a nonexistent session should not raise."""
        manager = TypingManager()
        # Should not raise
        await manager.stop_typing("nonexistent-session")

    async def test_start_typing_replaces_existing(self):
        """Starting typing for an existing session should cancel the old task first."""
        provider = _make_mock_provider()
        manager = TypingManager(interval=0.05)

        await manager.start_typing(provider, "channel-123", "session-1")
        old_task = manager._active_tasks["session-1"]

        await manager.start_typing(provider, "channel-456", "session-1")
        new_task = manager._active_tasks["session-1"]

        assert old_task is not new_task
        assert old_task.cancelled() or old_task.done()

        await manager.stop_typing("session-1")

    async def test_multiple_sessions(self):
        """Multiple concurrent typing sessions should be tracked independently."""
        provider = _make_mock_provider()
        manager = TypingManager(interval=0.05)

        await manager.start_typing(provider, "ch-1", "session-a")
        await manager.start_typing(provider, "ch-2", "session-b")

        assert "session-a" in manager._active_tasks
        assert "session-b" in manager._active_tasks

        await manager.stop_typing("session-a")
        assert "session-a" not in manager._active_tasks
        assert "session-b" in manager._active_tasks

        await manager.stop_typing("session-b")
        assert "session-b" not in manager._active_tasks

    async def test_typing_with_provider_lacking_typing_start(self):
        """If provider has no typing_start method, the loop should not crash."""
        provider = _make_mock_provider(has_typing=False)
        manager = TypingManager(interval=0.05)

        await manager.start_typing(provider, "channel-123", "session-1")
        await asyncio.sleep(0.1)
        await manager.stop_typing("session-1")
        # No exception means success

    async def test_typing_loop_handles_provider_exception(self):
        """The typing loop should not die if provider.typing_start raises."""
        provider = _make_mock_provider()
        provider.typing_start.side_effect = RuntimeError("Connection lost")

        manager = TypingManager(interval=0.05)
        await manager.start_typing(provider, "channel-123", "session-1")
        await asyncio.sleep(0.15)

        # Loop should still be running despite the error
        assert "session-1" in manager._active_tasks
        assert not manager._active_tasks["session-1"].done()

        await manager.stop_typing("session-1")

    async def test_custom_interval(self):
        """TypingManager should use the configured interval."""
        manager = TypingManager(interval=5.0)
        assert manager.interval == 5.0

    async def test_default_interval(self):
        """Default interval should be 3.0 seconds."""
        manager = TypingManager()
        assert manager.interval == 3.0


# ===========================================================================
# ReactionManager tests
# ===========================================================================

class TestReactionManager:
    """Tests for ReactionManager."""

    # -- acknowledge --------------------------------------------------------

    async def test_acknowledge_calls_react(self):
        """acknowledge should call provider.react with the ack emoji."""
        provider = _make_mock_provider()
        manager = ReactionManager()

        await manager.acknowledge(provider, "ch-1", "msg-1")
        provider.react.assert_called_once_with("ch-1", "msg-1", ACK_REACTION)

    async def test_acknowledge_with_custom_emoji(self):
        """Custom ack emoji should be used."""
        provider = _make_mock_provider()
        manager = ReactionManager(ack_emoji="thumbsup")

        await manager.acknowledge(provider, "ch-1", "msg-1")
        provider.react.assert_called_once_with("ch-1", "msg-1", "thumbsup")

    async def test_acknowledge_no_react_method(self):
        """If provider lacks a react method, acknowledge should silently skip."""
        provider = _make_mock_provider(has_react=False)
        manager = ReactionManager()

        # Should not raise
        await manager.acknowledge(provider, "ch-1", "msg-1")

    async def test_acknowledge_handles_exception(self):
        """If provider.react raises, acknowledge should not propagate."""
        provider = _make_mock_provider()
        provider.react.side_effect = RuntimeError("API error")
        manager = ReactionManager()

        # Should not raise
        await manager.acknowledge(provider, "ch-1", "msg-1")

    # -- mark_done ----------------------------------------------------------

    async def test_mark_done_calls_react(self):
        """mark_done should call provider.react with the done emoji."""
        provider = _make_mock_provider()
        manager = ReactionManager()

        await manager.mark_done(provider, "ch-1", "msg-1")
        provider.react.assert_called_once_with("ch-1", "msg-1", DONE_REACTION)

    async def test_mark_done_with_custom_emoji(self):
        """Custom done emoji should be used."""
        provider = _make_mock_provider()
        manager = ReactionManager(done_emoji="checkmark")

        await manager.mark_done(provider, "ch-1", "msg-1")
        provider.react.assert_called_once_with("ch-1", "msg-1", "checkmark")

    async def test_mark_done_no_react_method(self):
        """If provider lacks react, mark_done should silently skip."""
        provider = _make_mock_provider(has_react=False)
        manager = ReactionManager()

        await manager.mark_done(provider, "ch-1", "msg-1")

    async def test_mark_done_handles_exception(self):
        """mark_done should swallow provider exceptions."""
        provider = _make_mock_provider()
        provider.react.side_effect = ConnectionError("Timeout")
        manager = ReactionManager()

        await manager.mark_done(provider, "ch-1", "msg-1")

    # -- mark_error ---------------------------------------------------------

    async def test_mark_error_calls_react(self):
        """mark_error should call provider.react with the error emoji."""
        provider = _make_mock_provider()
        manager = ReactionManager()

        await manager.mark_error(provider, "ch-1", "msg-1")
        provider.react.assert_called_once_with("ch-1", "msg-1", ERROR_REACTION)

    async def test_mark_error_with_custom_emoji(self):
        """Custom error emoji should be used."""
        provider = _make_mock_provider()
        manager = ReactionManager(error_emoji="warning")

        await manager.mark_error(provider, "ch-1", "msg-1")
        provider.react.assert_called_once_with("ch-1", "msg-1", "warning")

    async def test_mark_error_no_react_method(self):
        """If provider lacks react, mark_error should silently skip."""
        provider = _make_mock_provider(has_react=False)
        manager = ReactionManager()

        await manager.mark_error(provider, "ch-1", "msg-1")

    async def test_mark_error_handles_exception(self):
        """mark_error should swallow provider exceptions."""
        provider = _make_mock_provider()
        provider.react.side_effect = Exception("Unexpected")
        manager = ReactionManager()

        await manager.mark_error(provider, "ch-1", "msg-1")

    # -- default emoji constants --------------------------------------------

    def test_default_emoji_constants(self):
        """Verify the default reaction emoji constants."""
        assert ACK_REACTION == "eyes"
        assert DONE_REACTION == "white_check_mark"
        assert ERROR_REACTION == "x"

    def test_default_manager_emojis(self):
        """Default ReactionManager should use the standard emojis."""
        manager = ReactionManager()
        assert manager.ack_emoji == "eyes"
        assert manager.done_emoji == "white_check_mark"
        assert manager.error_emoji == "x"

    # -- full workflow ------------------------------------------------------

    async def test_full_ack_done_workflow(self):
        """Simulate ack then done workflow on same message."""
        provider = _make_mock_provider()
        manager = ReactionManager()

        await manager.acknowledge(provider, "ch-1", "msg-1")
        await manager.mark_done(provider, "ch-1", "msg-1")

        assert provider.react.call_count == 2
        calls = [c.args for c in provider.react.call_args_list]
        assert ("ch-1", "msg-1", ACK_REACTION) in calls
        assert ("ch-1", "msg-1", DONE_REACTION) in calls

    async def test_full_ack_error_workflow(self):
        """Simulate ack then error workflow on same message."""
        provider = _make_mock_provider()
        manager = ReactionManager()

        await manager.acknowledge(provider, "ch-1", "msg-1")
        await manager.mark_error(provider, "ch-1", "msg-1")

        assert provider.react.call_count == 2
        calls = [c.args for c in provider.react.call_args_list]
        assert ("ch-1", "msg-1", ACK_REACTION) in calls
        assert ("ch-1", "msg-1", ERROR_REACTION) in calls


# ===========================================================================
# CommandGate tests
# ===========================================================================

class TestCommandGate:
    """Tests for CommandGate."""

    # -- default permissions ------------------------------------------------

    def test_default_direct_allows_all(self):
        """Direct messages should allow all commands by default (wildcard)."""
        gate = CommandGate()
        assert gate.is_allowed("model", chat_type="direct")
        assert gate.is_allowed("reset", chat_type="direct")
        assert gate.is_allowed("admin", chat_type="direct")
        assert gate.is_allowed("anything", chat_type="direct")

    def test_default_group_limited(self):
        """Group chats should only allow help, status, model by default."""
        gate = CommandGate()
        assert gate.is_allowed("help", chat_type="group")
        assert gate.is_allowed("status", chat_type="group")
        assert gate.is_allowed("model", chat_type="group")

    def test_default_group_denies_reset(self):
        """Group chats should deny commands not in the allowed set."""
        gate = CommandGate()
        assert not gate.is_allowed("reset", chat_type="group")
        assert not gate.is_allowed("compact", chat_type="group")
        assert not gate.is_allowed("admin", chat_type="group")

    def test_default_permissions_structure(self):
        """Verify DEFAULT_PERMISSIONS has the expected structure."""
        assert "direct" in DEFAULT_PERMISSIONS
        assert "*" in DEFAULT_PERMISSIONS["direct"]
        assert "group" in DEFAULT_PERMISSIONS
        assert "help" in DEFAULT_PERMISSIONS["group"]
        assert "status" in DEFAULT_PERMISSIONS["group"]
        assert "model" in DEFAULT_PERMISSIONS["group"]

    # -- admin bypass -------------------------------------------------------

    def test_admin_bypasses_group_restrictions(self):
        """Admin users should bypass all command restrictions."""
        gate = CommandGate(admin_users={"user-admin"})
        assert gate.is_allowed("reset", chat_type="group", sender_id="user-admin")
        assert gate.is_allowed("compact", chat_type="group", sender_id="user-admin")
        assert gate.is_allowed("anything", chat_type="group", sender_id="user-admin")

    def test_non_admin_still_restricted(self):
        """Non-admin users should still be restricted."""
        gate = CommandGate(admin_users={"user-admin"})
        assert not gate.is_allowed("reset", chat_type="group", sender_id="user-regular")

    def test_admin_with_none_sender(self):
        """None sender_id should not trigger admin bypass."""
        gate = CommandGate(admin_users={"user-admin"})
        assert not gate.is_allowed("reset", chat_type="group", sender_id=None)

    # -- custom permissions -------------------------------------------------

    def test_custom_permissions(self):
        """Custom permission map should override defaults."""
        perms = {
            "direct": {"help", "ping"},
            "group": {"help"},
        }
        gate = CommandGate(permissions=perms)

        assert gate.is_allowed("help", chat_type="direct")
        assert gate.is_allowed("ping", chat_type="direct")
        assert not gate.is_allowed("reset", chat_type="direct")

        assert gate.is_allowed("help", chat_type="group")
        assert not gate.is_allowed("ping", chat_type="group")

    def test_wildcard_in_custom_permissions(self):
        """Wildcard in custom permissions should allow everything."""
        perms = {"group": {"*"}}
        gate = CommandGate(permissions=perms)
        assert gate.is_allowed("anything", chat_type="group")
        assert gate.is_allowed("reset", chat_type="group")

    def test_empty_permissions_denies_all(self):
        """Empty permission set should deny all commands."""
        perms = {"group": set()}
        gate = CommandGate(permissions=perms)
        assert not gate.is_allowed("help", chat_type="group")
        assert not gate.is_allowed("status", chat_type="group")

    def test_unknown_chat_type_denies(self):
        """An unknown chat_type not in permissions should deny all."""
        gate = CommandGate()
        assert not gate.is_allowed("help", chat_type="broadcast")

    # -- channel-specific overrides -----------------------------------------

    def test_channel_specific_override(self):
        """Channel-specific keys (channel:chat_type) should override chat_type defaults."""
        perms = {
            "group": {"help", "status"},
            "discord:group": {"help", "status", "reset", "model"},
        }
        gate = CommandGate(permissions=perms)

        # discord:group allows reset
        assert gate.is_allowed("reset", chat_type="group", channel="discord")
        # generic group does not
        assert not gate.is_allowed("reset", chat_type="group", channel="slack")

    def test_channel_specific_with_wildcard(self):
        """Channel-specific wildcard should allow all."""
        perms = {
            "group": {"help"},
            "discord:group": {"*"},
        }
        gate = CommandGate(permissions=perms)
        assert gate.is_allowed("anything", chat_type="group", channel="discord")

    def test_channel_specific_falls_back_to_chat_type(self):
        """When no channel-specific key exists, fall back to chat_type permissions."""
        perms = {
            "group": {"help", "status"},
        }
        gate = CommandGate(permissions=perms)
        # No "discord:group" key, so falls back to "group"
        assert gate.is_allowed("help", chat_type="group", channel="discord")
        assert not gate.is_allowed("reset", chat_type="group", channel="discord")

    # -- case insensitivity -------------------------------------------------

    def test_command_case_insensitive(self):
        """Commands should be checked case-insensitively."""
        gate = CommandGate()
        assert gate.is_allowed("HELP", chat_type="group")
        assert gate.is_allowed("Help", chat_type="group")
        assert gate.is_allowed("STATUS", chat_type="group")

    # -- add_permission / remove_permission ---------------------------------

    def test_add_permission(self):
        """add_permission should add a command to the allowed set."""
        gate = CommandGate()
        assert not gate.is_allowed("reset", chat_type="group")

        gate.add_permission("group", "reset")
        assert gate.is_allowed("reset", chat_type="group")

    def test_add_permission_channel_specific(self):
        """add_permission with channel should create a channel-specific key."""
        gate = CommandGate()
        gate.add_permission("group", "reset", channel="discord")
        assert gate.is_allowed("reset", chat_type="group", channel="discord")

    def test_remove_permission(self):
        """remove_permission should remove a command from the allowed set."""
        gate = CommandGate()
        assert gate.is_allowed("help", chat_type="group")

        gate.remove_permission("group", "help")
        assert not gate.is_allowed("help", chat_type="group")

    def test_remove_permission_channel_specific(self):
        """remove_permission with channel should target the channel-specific key."""
        perms = {
            "group": {"help"},
            "discord:group": {"help", "reset"},
        }
        gate = CommandGate(permissions=perms)

        gate.remove_permission("group", "reset", channel="discord")
        assert not gate.is_allowed("reset", chat_type="group", channel="discord")
        # chat_type "group" still has "help" (not reset, which was never there)
        assert gate.is_allowed("help", chat_type="group")

    def test_remove_nonexistent_permission(self):
        """Removing a permission that doesn't exist should not raise."""
        gate = CommandGate()
        # "reset" is not in "group" by default
        gate.remove_permission("group", "reset")
        # And removing from a nonexistent key should also be safe
        gate.remove_permission("nonexistent", "help")

    def test_add_permission_lowercases(self):
        """add_permission should lowercase the command."""
        gate = CommandGate()
        gate.add_permission("group", "RESET")
        assert gate.is_allowed("reset", chat_type="group")

    def test_remove_permission_lowercases(self):
        """remove_permission should lowercase the command before removing."""
        perms = {"group": {"help", "status", "model"}}
        gate = CommandGate(permissions=perms)
        assert gate.is_allowed("help", chat_type="group")
        gate.remove_permission("group", "HELP")
        assert not gate.is_allowed("help", chat_type="group")
        # Other permissions unaffected
        assert gate.is_allowed("status", chat_type="group")


# ===========================================================================
# MentionGate tests
# ===========================================================================

class TestMentionGate:
    """Tests for MentionGate."""

    # -- direct messages always pass ----------------------------------------

    def test_direct_always_passes(self):
        """Direct messages should always be processed."""
        gate = MentionGate(bot_ids={"bot-1"})
        assert gate.should_process("Hello", chat_type="direct")

    def test_direct_passes_without_mention(self):
        """Direct messages pass even without any mention."""
        gate = MentionGate(bot_ids={"bot-1"}, require_in_groups=True)
        assert gate.should_process("Just chatting", chat_type="direct")

    # -- group: require_in_groups disabled ----------------------------------

    def test_group_no_requirement(self):
        """Groups should pass all messages when require_in_groups is False."""
        gate = MentionGate(bot_ids={"bot-1"}, require_in_groups=False)
        assert gate.should_process("No mention here", chat_type="group")

    # -- group: mention by ID in mentioned_ids ------------------------------

    def test_group_mentioned_by_id(self):
        """Group message should pass when bot ID is in mentioned_ids."""
        gate = MentionGate(bot_ids={"bot-1"})
        assert gate.should_process(
            "Hey there",
            chat_type="group",
            mentioned_ids=["bot-1"],
        )

    def test_group_not_mentioned_by_id(self):
        """Group message should be blocked when bot ID not in mentioned_ids."""
        gate = MentionGate(bot_ids={"bot-1"})
        assert not gate.should_process(
            "Hey there",
            chat_type="group",
            mentioned_ids=["other-user"],
        )

    def test_group_no_mentioned_ids(self):
        """Group message with no mentioned_ids and no text mention should be blocked."""
        gate = MentionGate(bot_ids={"bot-1"})
        assert not gate.should_process(
            "Hey there",
            chat_type="group",
            mentioned_ids=None,
        )

    def test_group_empty_mentioned_ids(self):
        """Group message with empty mentioned_ids should be blocked."""
        gate = MentionGate(bot_ids={"bot-1"})
        assert not gate.should_process(
            "Hey there",
            chat_type="group",
            mentioned_ids=[],
        )

    # -- group: mention by name in text -------------------------------------

    def test_group_mentioned_by_name(self):
        """Group message containing bot name should pass."""
        gate = MentionGate(bot_names={"ungula"})
        assert gate.should_process(
            "Hey ungula, what's up?",
            chat_type="group",
        )

    def test_group_name_case_insensitive(self):
        """Bot name detection should be case-insensitive."""
        gate = MentionGate(bot_names={"Ungula"})
        assert gate.should_process("hey UNGULA!", chat_type="group")
        assert gate.should_process("hey ungula!", chat_type="group")

    def test_group_name_not_present(self):
        """Group message without bot name should be blocked."""
        gate = MentionGate(bot_names={"ungula"})
        assert not gate.should_process("Hey everyone", chat_type="group")

    # -- group: @mention patterns in text -----------------------------------

    def test_group_discord_style_mention(self):
        """Discord-style <@bot_id> should be detected."""
        gate = MentionGate(bot_ids={"123456"})
        assert gate.should_process(
            "Hey <@123456> help me",
            chat_type="group",
        )

    def test_group_at_mention(self):
        """Plain @bot_id in text should be detected."""
        gate = MentionGate(bot_ids={"bot-1"})
        assert gate.should_process(
            "Hey @bot-1 what's up",
            chat_type="group",
        )

    def test_group_mention_pattern_wrong_id(self):
        """@mention with wrong bot ID should not match."""
        gate = MentionGate(bot_ids={"bot-1"})
        assert not gate.should_process(
            "Hey <@bot-2> help",
            chat_type="group",
        )

    # -- multiple bot identifiers -------------------------------------------

    def test_multiple_bot_ids(self):
        """Any of multiple bot IDs in mentioned_ids should match."""
        gate = MentionGate(bot_ids={"bot-1", "bot-2"})
        assert gate.should_process(
            "Hello",
            chat_type="group",
            mentioned_ids=["bot-2"],
        )

    def test_multiple_bot_names(self):
        """Any of multiple bot names in text should match."""
        gate = MentionGate(bot_names={"ungula", "claw"})
        assert gate.should_process("Hey claw", chat_type="group")

    # -- no identifiers configured ------------------------------------------

    def test_no_identifiers_blocks_group(self):
        """With no bot_ids or bot_names, group messages should be blocked."""
        gate = MentionGate()
        assert not gate.should_process("Hello", chat_type="group")

    def test_no_identifiers_passes_direct(self):
        """With no identifiers, direct messages should still pass."""
        gate = MentionGate()
        assert gate.should_process("Hello", chat_type="direct")

    # -- strip_mention() ---------------------------------------------------

    def test_strip_discord_mention(self):
        """strip_mention should remove <@bot_id> patterns."""
        gate = MentionGate(bot_ids={"123456"})
        result = gate.strip_mention("Hey <@123456> help me")
        assert "<@123456>" not in result
        assert "help me" in result

    def test_strip_discord_excl_mention(self):
        """strip_mention should remove <@!bot_id> patterns (Discord nickname)."""
        gate = MentionGate(bot_ids={"123456"})
        result = gate.strip_mention("Hey <@!123456> help me")
        assert "<@!123456>" not in result
        assert "help me" in result

    def test_strip_at_name(self):
        """strip_mention should remove @name patterns."""
        gate = MentionGate(bot_names={"ungula"})
        result = gate.strip_mention("Hey @ungula help me")
        assert "@ungula" not in result
        assert "help me" in result

    def test_strip_at_name_case_insensitive(self):
        """strip_mention should handle case-insensitive @name removal."""
        gate = MentionGate(bot_names={"Ungula"})
        result = gate.strip_mention("Hey @UNGULA help me")
        assert "@UNGULA" not in result
        assert "help me" in result

    def test_strip_multiple_mentions(self):
        """strip_mention should remove all mention occurrences."""
        gate = MentionGate(bot_ids={"123"}, bot_names={"ungula"})
        result = gate.strip_mention("<@123> Hey @ungula what's up <@123>")
        assert "<@123>" not in result
        assert "@ungula" not in result
        assert "what's up" in result

    def test_strip_returns_stripped(self):
        """strip_mention result should be stripped of leading/trailing whitespace."""
        gate = MentionGate(bot_ids={"123"})
        result = gate.strip_mention("<@123> hello")
        assert result == "hello"

    def test_strip_mention_no_matches(self):
        """strip_mention with no matching mentions should return content unchanged."""
        gate = MentionGate(bot_ids={"123"})
        result = gate.strip_mention("Hello world")
        assert result == "Hello world"

    def test_strip_mention_only_mention(self):
        """strip_mention where content is only the mention should return empty."""
        gate = MentionGate(bot_ids={"123"})
        result = gate.strip_mention("<@123>")
        assert result == ""

    # -- edge cases ---------------------------------------------------------

    def test_empty_content_group(self):
        """Empty content in group should be blocked (no mention to find)."""
        gate = MentionGate(bot_ids={"bot-1"})
        assert not gate.should_process("", chat_type="group")

    def test_empty_content_direct(self):
        """Empty content in direct should still pass."""
        gate = MentionGate(bot_ids={"bot-1"})
        assert gate.should_process("", chat_type="direct")

    def test_bot_name_substring_match(self):
        """Bot name matching checks for substring presence in content."""
        gate = MentionGate(bot_names={"bot"})
        # "robot" contains "bot" as a substring -- this will match
        assert gate.should_process("Hey robot", chat_type="group")

    def test_multiple_mention_types_combined(self):
        """Gate should pass if any mention type matches."""
        gate = MentionGate(bot_ids={"123"}, bot_names={"ungula"})
        # ID mention
        assert gate.should_process("hi", chat_type="group", mentioned_ids=["123"])
        # Name mention
        assert gate.should_process("hey ungula", chat_type="group")
        # Pattern mention
        assert gate.should_process("<@123> hi", chat_type="group")
