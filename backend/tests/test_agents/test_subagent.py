"""
Tests for the subagent management system.

Covers SubagentSession, SubagentStatus, SubagentManager, and _run_subagent.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from ungula.agents.subagent import SubagentManager, SubagentSession, SubagentStatus


# ---------------------------------------------------------------------------
# SubagentStatus enum
# ---------------------------------------------------------------------------


class TestSubagentStatus:
    """Tests for the SubagentStatus enum."""

    def test_enum_values(self):
        """All expected status values exist."""
        assert SubagentStatus.PENDING == "pending"
        assert SubagentStatus.RUNNING == "running"
        assert SubagentStatus.COMPLETED == "completed"
        assert SubagentStatus.FAILED == "failed"
        assert SubagentStatus.CANCELLED == "cancelled"

    def test_enum_is_str(self):
        """SubagentStatus inherits from str, so values are plain strings."""
        assert isinstance(SubagentStatus.PENDING, str)
        assert SubagentStatus.RUNNING.value == "running"
        # Enum members compare equal to their string value
        assert SubagentStatus.RUNNING == "running"

    def test_enum_member_count(self):
        """There are exactly five statuses."""
        assert len(SubagentStatus) == 5


# ---------------------------------------------------------------------------
# SubagentSession dataclass
# ---------------------------------------------------------------------------


class TestSubagentSession:
    """Tests for SubagentSession creation and serialisation."""

    def test_defaults(self):
        """A new session has sensible defaults."""
        session = SubagentSession()
        assert isinstance(session.id, UUID)
        assert session.parent_conversation_id is None
        assert session.conversation_id is None
        assert session.task_description == ""
        assert session.status == SubagentStatus.PENDING
        assert session.result is None
        assert session.error is None
        assert isinstance(session.created_at, datetime)
        assert session.started_at is None
        assert session.completed_at is None
        assert session.metadata == {}

    def test_custom_values(self):
        """Session respects explicitly supplied values."""
        parent_id = uuid4()
        conv_id = uuid4()
        now = datetime.now(UTC)
        session = SubagentSession(
            parent_conversation_id=parent_id,
            conversation_id=conv_id,
            task_description="Analyse codebase",
            status=SubagentStatus.RUNNING,
            result="done",
            error=None,
            created_at=now,
            started_at=now,
            metadata={"priority": "high"},
        )
        assert session.parent_conversation_id == parent_id
        assert session.conversation_id == conv_id
        assert session.task_description == "Analyse codebase"
        assert session.status == SubagentStatus.RUNNING
        assert session.result == "done"
        assert session.metadata == {"priority": "high"}

    def test_to_dict_all_none_optionals(self):
        """to_dict handles None optionals gracefully."""
        session = SubagentSession(task_description="test")
        d = session.to_dict()

        assert d["id"] == str(session.id)
        assert d["parent_conversation_id"] is None
        assert d["conversation_id"] is None
        assert d["task_description"] == "test"
        assert d["status"] == "pending"
        assert d["result"] is None
        assert d["error"] is None
        assert isinstance(d["created_at"], str)
        assert d["started_at"] is None
        assert d["completed_at"] is None

    def test_to_dict_with_populated_fields(self):
        """to_dict serialises UUIDs and datetimes correctly."""
        parent_id = uuid4()
        conv_id = uuid4()
        now = datetime.now(UTC)
        session = SubagentSession(
            parent_conversation_id=parent_id,
            conversation_id=conv_id,
            task_description="build feature",
            status=SubagentStatus.COMPLETED,
            result="Feature built",
            error=None,
            created_at=now,
            started_at=now,
            completed_at=now,
        )
        d = session.to_dict()

        assert d["parent_conversation_id"] == str(parent_id)
        assert d["conversation_id"] == str(conv_id)
        assert d["status"] == "completed"
        assert d["result"] == "Feature built"
        assert d["started_at"] == now.isoformat()
        assert d["completed_at"] == now.isoformat()

    def test_to_dict_does_not_include_metadata(self):
        """to_dict intentionally omits the metadata field."""
        session = SubagentSession(metadata={"key": "val"})
        d = session.to_dict()
        assert "metadata" not in d

    def test_unique_ids_per_instance(self):
        """Each session gets a unique UUID."""
        sessions = [SubagentSession() for _ in range(10)]
        ids = {s.id for s in sessions}
        assert len(ids) == 10


# ---------------------------------------------------------------------------
# SubagentManager
# ---------------------------------------------------------------------------


class TestSubagentManagerInit:
    """Tests for SubagentManager initialisation."""

    def test_default_max_concurrent(self):
        mgr = SubagentManager()
        assert mgr.max_concurrent == 5

    def test_custom_max_concurrent(self):
        mgr = SubagentManager(max_concurrent=10)
        assert mgr.max_concurrent == 10

    def test_starts_empty(self):
        mgr = SubagentManager()
        assert len(mgr._sessions) == 0
        assert len(mgr._tasks) == 0


class TestSubagentManagerSpawn:
    """Tests for SubagentManager.spawn."""

    @pytest.mark.asyncio
    async def test_spawn_without_storage_or_runner(self):
        """Spawn succeeds with minimal args -- no storage, no runner."""
        mgr = SubagentManager()
        session = await mgr.spawn(task_description="Do something")

        assert session.task_description == "Do something"
        assert session.status == SubagentStatus.PENDING
        assert session.id in mgr._sessions
        # No task was created because agent_runner was None
        assert session.id not in mgr._tasks

    @pytest.mark.asyncio
    async def test_spawn_with_storage_creates_conversation(self):
        """When storage is provided, a conversation is created."""
        mock_storage = AsyncMock()
        mock_conv = MagicMock()
        mock_conv.id = uuid4()
        mock_storage.create_conversation.return_value = mock_conv

        mgr = SubagentManager()
        parent_id = uuid4()
        session = await mgr.spawn(
            task_description="Research topic",
            parent_conversation_id=parent_id,
            storage=mock_storage,
        )

        mock_storage.create_conversation.assert_awaited_once()
        call_args = mock_storage.create_conversation.call_args[0][0]
        assert "Subagent: Research topic" in call_args.title
        assert session.conversation_id == mock_conv.id
        assert session.parent_conversation_id == parent_id

    @pytest.mark.asyncio
    async def test_spawn_with_runner_creates_task(self):
        """When agent_runner + conversation_id exist, an asyncio.Task is created."""
        mock_storage = AsyncMock()
        mock_conv = MagicMock()
        mock_conv.id = uuid4()
        mock_storage.create_conversation.return_value = mock_conv

        mock_runner = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "Result text"
        mock_runner.run.return_value = mock_response

        mgr = SubagentManager()
        session = await mgr.spawn(
            task_description="Run analysis",
            agent_runner=mock_runner,
            storage=mock_storage,
        )

        assert session.id in mgr._tasks
        # Let the spawned task complete
        await mgr._tasks[session.id]
        assert session.status == SubagentStatus.COMPLETED
        assert session.result == "Result text"

    @pytest.mark.asyncio
    async def test_spawn_stores_metadata(self):
        """Metadata is forwarded to the session."""
        mgr = SubagentManager()
        session = await mgr.spawn(
            task_description="meta test",
            metadata={"priority": 1, "tag": "test"},
        )
        assert session.metadata == {"priority": 1, "tag": "test"}

    @pytest.mark.asyncio
    async def test_spawn_metadata_defaults_to_empty_dict(self):
        """When no metadata is supplied, an empty dict is used."""
        mgr = SubagentManager()
        session = await mgr.spawn(task_description="no meta")
        assert session.metadata == {}

    @pytest.mark.asyncio
    async def test_spawn_title_truncated_to_50_chars(self):
        """The conversation title uses the first 50 chars of the description."""
        mock_storage = AsyncMock()
        mock_conv = MagicMock()
        mock_conv.id = uuid4()
        mock_storage.create_conversation.return_value = mock_conv

        long_desc = "A" * 100
        mgr = SubagentManager()
        await mgr.spawn(task_description=long_desc, storage=mock_storage)

        call_args = mock_storage.create_conversation.call_args[0][0]
        # Title should be "Subagent: " + first 50 chars
        assert call_args.title == f"Subagent: {long_desc[:50]}"


class TestSubagentManagerConcurrencyLimit:
    """Tests for concurrent subagent limit enforcement."""

    @pytest.mark.asyncio
    async def test_respects_max_concurrent(self):
        """Cannot spawn more subagents than the configured limit."""
        mgr = SubagentManager(max_concurrent=2)

        # Manually inject two RUNNING sessions
        for _ in range(2):
            s = SubagentSession(status=SubagentStatus.RUNNING)
            mgr._sessions[s.id] = s

        with pytest.raises(RuntimeError, match="Max concurrent subagents"):
            await mgr.spawn(task_description="one too many")

    @pytest.mark.asyncio
    async def test_completed_sessions_dont_count(self):
        """Completed / failed / cancelled sessions do not count toward the limit."""
        mgr = SubagentManager(max_concurrent=1)

        for status in (SubagentStatus.COMPLETED, SubagentStatus.FAILED, SubagentStatus.CANCELLED):
            s = SubagentSession(status=status)
            mgr._sessions[s.id] = s

        # Should succeed because none of the existing sessions are RUNNING
        session = await mgr.spawn(task_description="should work")
        assert session is not None

    @pytest.mark.asyncio
    async def test_pending_sessions_dont_count(self):
        """PENDING sessions are not counted as active."""
        mgr = SubagentManager(max_concurrent=1)
        s = SubagentSession(status=SubagentStatus.PENDING)
        mgr._sessions[s.id] = s

        session = await mgr.spawn(task_description="allowed")
        assert session is not None

    @pytest.mark.asyncio
    async def test_max_concurrent_of_zero(self):
        """A limit of zero means no subagents can be spawned while any are running."""
        mgr = SubagentManager(max_concurrent=0)
        # With no running sessions, active count is 0 and limit is 0 so 0 >= 0 blocks it
        with pytest.raises(RuntimeError, match="Max concurrent subagents"):
            await mgr.spawn(task_description="nope")


class TestSubagentManagerGetSession:
    """Tests for SubagentManager.get_session."""

    @pytest.mark.asyncio
    async def test_returns_session_by_id(self):
        mgr = SubagentManager()
        session = await mgr.spawn(task_description="find me")
        found = await mgr.get_session(session.id)
        assert found is session

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_id(self):
        mgr = SubagentManager()
        result = await mgr.get_session(uuid4())
        assert result is None


class TestSubagentManagerListSessions:
    """Tests for SubagentManager.list_sessions with filtering."""

    @pytest.mark.asyncio
    async def test_list_all(self):
        mgr = SubagentManager()
        await mgr.spawn(task_description="a")
        await mgr.spawn(task_description="b")
        sessions = await mgr.list_sessions()
        assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_filter_by_parent_id(self):
        mgr = SubagentManager()
        parent_a = uuid4()
        parent_b = uuid4()
        await mgr.spawn(task_description="a1", parent_conversation_id=parent_a)
        await mgr.spawn(task_description="a2", parent_conversation_id=parent_a)
        await mgr.spawn(task_description="b1", parent_conversation_id=parent_b)

        results = await mgr.list_sessions(parent_id=parent_a)
        assert len(results) == 2
        assert all(s.parent_conversation_id == parent_a for s in results)

    @pytest.mark.asyncio
    async def test_filter_by_status(self):
        mgr = SubagentManager()
        s1 = await mgr.spawn(task_description="pending")
        s2 = await mgr.spawn(task_description="also pending")

        # Manually mark one as completed
        s1.status = SubagentStatus.COMPLETED

        pending = await mgr.list_sessions(status=SubagentStatus.PENDING)
        completed = await mgr.list_sessions(status=SubagentStatus.COMPLETED)

        assert len(pending) == 1
        assert pending[0].id == s2.id
        assert len(completed) == 1
        assert completed[0].id == s1.id

    @pytest.mark.asyncio
    async def test_filter_by_parent_and_status(self):
        mgr = SubagentManager()
        parent = uuid4()
        s1 = await mgr.spawn(task_description="x", parent_conversation_id=parent)
        s2 = await mgr.spawn(task_description="y", parent_conversation_id=parent)
        s1.status = SubagentStatus.COMPLETED

        results = await mgr.list_sessions(parent_id=parent, status=SubagentStatus.COMPLETED)
        assert len(results) == 1
        assert results[0].id == s1.id

    @pytest.mark.asyncio
    async def test_sorted_by_created_at_descending(self):
        """Results are sorted newest-first."""
        mgr = SubagentManager()
        s1 = await mgr.spawn(task_description="first")
        s2 = await mgr.spawn(task_description="second")

        # Force distinct timestamps
        s1.created_at = datetime(2024, 1, 1, tzinfo=UTC)
        s2.created_at = datetime(2024, 6, 1, tzinfo=UTC)

        sessions = await mgr.list_sessions()
        assert sessions[0].id == s2.id
        assert sessions[1].id == s1.id

    @pytest.mark.asyncio
    async def test_empty_when_no_match(self):
        mgr = SubagentManager()
        await mgr.spawn(task_description="test")
        result = await mgr.list_sessions(status=SubagentStatus.FAILED)
        assert result == []


class TestSubagentManagerCancel:
    """Tests for SubagentManager.cancel."""

    @pytest.mark.asyncio
    async def test_cancel_unknown_session(self):
        mgr = SubagentManager()
        result = await mgr.cancel(uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_session_without_task(self):
        """Cancelling a session that has no asyncio.Task still sets status."""
        mgr = SubagentManager()
        session = await mgr.spawn(task_description="no runner")

        result = await mgr.cancel(session.id)
        assert result is True
        assert session.status == SubagentStatus.CANCELLED
        assert session.completed_at is not None

    @pytest.mark.asyncio
    async def test_cancel_running_task(self):
        """Cancelling a session with a running asyncio.Task cancels the task."""
        mgr = SubagentManager()
        session = SubagentSession(
            task_description="slow work",
            status=SubagentStatus.RUNNING,
        )
        mgr._sessions[session.id] = session

        # Create a long-running task
        async def slow_work():
            await asyncio.sleep(3600)

        task = asyncio.create_task(slow_work())
        mgr._tasks[session.id] = task

        result = await mgr.cancel(session.id)
        assert result is True
        assert session.status == SubagentStatus.CANCELLED
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_cancel_already_done_task(self):
        """Cancelling after the task already finished still updates status."""
        mgr = SubagentManager()
        session = SubagentSession(
            task_description="done",
            status=SubagentStatus.COMPLETED,
        )
        mgr._sessions[session.id] = session

        # Already completed task
        async def noop():
            pass

        task = asyncio.create_task(noop())
        await task  # Let it complete
        mgr._tasks[session.id] = task

        result = await mgr.cancel(session.id)
        assert result is True
        # Status overwritten to CANCELLED regardless
        assert session.status == SubagentStatus.CANCELLED


class TestSubagentManagerCollectResult:
    """Tests for SubagentManager.collect_result."""

    @pytest.mark.asyncio
    async def test_collect_unknown_session(self):
        mgr = SubagentManager()
        result = await mgr.collect_result(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_collect_already_completed(self):
        """Collect result from a session whose task already finished."""
        mgr = SubagentManager()
        session = SubagentSession(
            task_description="done",
            status=SubagentStatus.COMPLETED,
            result="the answer",
        )
        mgr._sessions[session.id] = session
        # No task registered

        result = await mgr.collect_result(session.id)
        assert result == "the answer"

    @pytest.mark.asyncio
    async def test_collect_waits_for_running_task(self):
        """collect_result waits for the task to complete."""
        mgr = SubagentManager()

        mock_runner = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "waited result"
        mock_runner.run.return_value = mock_response

        mock_storage = AsyncMock()
        mock_conv = MagicMock()
        mock_conv.id = uuid4()
        mock_storage.create_conversation.return_value = mock_conv

        session = await mgr.spawn(
            task_description="wait for me",
            agent_runner=mock_runner,
            storage=mock_storage,
        )

        result = await mgr.collect_result(session.id)
        assert result == "waited result"

    @pytest.mark.asyncio
    async def test_collect_timeout_marks_failed(self):
        """When the task takes too long, collect_result marks it failed."""
        mgr = SubagentManager()
        session = SubagentSession(
            task_description="slow",
            status=SubagentStatus.RUNNING,
        )
        mgr._sessions[session.id] = session

        async def hang_forever():
            await asyncio.sleep(3600)

        task = asyncio.create_task(hang_forever())
        mgr._tasks[session.id] = task

        # Patch wait_for to time out immediately
        with patch("ungula.agents.subagent.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            result = await mgr.collect_result(session.id)

        assert result is None  # session.result was never set
        assert session.status == SubagentStatus.FAILED
        assert session.error == "Timed out waiting for result"

        # Clean up the dangling task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# _run_subagent internal method
# ---------------------------------------------------------------------------


class TestRunSubagent:
    """Tests for SubagentManager._run_subagent."""

    @pytest.mark.asyncio
    async def test_success_path(self):
        """On success, session transitions RUNNING -> COMPLETED with result."""
        mgr = SubagentManager()
        session = SubagentSession(
            task_description="do it",
            conversation_id=uuid4(),
        )

        mock_runner = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "All done"
        mock_runner.run.return_value = mock_response

        await mgr._run_subagent(session, mock_runner)

        assert session.status == SubagentStatus.COMPLETED
        assert session.result == "All done"
        assert session.started_at is not None
        assert session.completed_at is not None
        assert session.completed_at >= session.started_at

        mock_runner.run.assert_awaited_once_with(
            conversation_id=session.conversation_id,
            user_message=session.task_description,
        )

    @pytest.mark.asyncio
    async def test_failure_path(self):
        """On exception, session transitions RUNNING -> FAILED with error."""
        mgr = SubagentManager()
        session = SubagentSession(
            task_description="fail",
            conversation_id=uuid4(),
        )

        mock_runner = AsyncMock()
        mock_runner.run.side_effect = ValueError("LLM provider error")

        await mgr._run_subagent(session, mock_runner)

        assert session.status == SubagentStatus.FAILED
        assert session.error == "LLM provider error"
        assert session.started_at is not None
        assert session.completed_at is not None
        assert session.result is None

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self):
        """CancelledError re-raises after marking status."""
        mgr = SubagentManager()
        session = SubagentSession(
            task_description="cancel me",
            conversation_id=uuid4(),
        )

        mock_runner = AsyncMock()
        mock_runner.run.side_effect = asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await mgr._run_subagent(session, mock_runner)

        assert session.status == SubagentStatus.CANCELLED
        assert session.completed_at is not None

    @pytest.mark.asyncio
    async def test_sets_started_at_before_running(self):
        """started_at is set before calling agent_runner.run."""
        mgr = SubagentManager()
        session = SubagentSession(
            task_description="timing test",
            conversation_id=uuid4(),
        )

        captured_started_at = None

        async def capture_time(**kwargs):
            nonlocal captured_started_at
            captured_started_at = session.started_at
            resp = MagicMock()
            resp.content = "ok"
            return resp

        mock_runner = AsyncMock()
        mock_runner.run.side_effect = capture_time

        await mgr._run_subagent(session, mock_runner)

        # started_at was set before run() executed
        assert captured_started_at is not None
        assert session.status == SubagentStatus.RUNNING or session.status == SubagentStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_empty_result_content(self):
        """Handles empty response content without error."""
        mgr = SubagentManager()
        session = SubagentSession(
            task_description="empty response",
            conversation_id=uuid4(),
        )

        mock_runner = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = ""
        mock_runner.run.return_value = mock_response

        await mgr._run_subagent(session, mock_runner)

        assert session.status == SubagentStatus.COMPLETED
        assert session.result == ""
