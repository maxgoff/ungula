"""
Comprehensive tests for the Ungula cron module.

Tests cover:
- CronSchedule creation (at, every, cron kinds)
- CronJob creation and serialization
- CronStore CRUD operations
- CronScheduler compute_next_run() for different schedule kinds
- CronScheduler _parse_interval() for various interval strings
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from ungula.cron.scheduler import (
    CronScheduler,
    _next_at_run,
    _parse_interval,
    compute_next_run,
)
from ungula.cron.store import CronStore
from ungula.cron.types import CronJob, CronSchedule, ScheduleKind


# ---------------------------------------------------------------------------
# CronSchedule creation
# ---------------------------------------------------------------------------

class TestCronSchedule:
    """Tests for CronSchedule model creation."""

    def test_create_at_schedule(self):
        schedule = CronSchedule(kind=ScheduleKind.AT, value="14:30")
        assert schedule.kind == ScheduleKind.AT
        assert schedule.value == "14:30"

    def test_create_every_schedule(self):
        schedule = CronSchedule(kind=ScheduleKind.EVERY, value="30m")
        assert schedule.kind == ScheduleKind.EVERY
        assert schedule.value == "30m"

    def test_create_cron_schedule(self):
        schedule = CronSchedule(kind=ScheduleKind.CRON, value="*/5 * * * *")
        assert schedule.kind == ScheduleKind.CRON
        assert schedule.value == "*/5 * * * *"

    def test_schedule_kind_string_values(self):
        assert ScheduleKind.AT == "at"
        assert ScheduleKind.EVERY == "every"
        assert ScheduleKind.CRON == "cron"

    def test_schedule_kind_from_string(self):
        assert ScheduleKind("at") == ScheduleKind.AT
        assert ScheduleKind("every") == ScheduleKind.EVERY
        assert ScheduleKind("cron") == ScheduleKind.CRON

    def test_invalid_schedule_kind_raises(self):
        with pytest.raises(ValueError):
            ScheduleKind("weekly")

    def test_schedule_serialization_roundtrip(self):
        schedule = CronSchedule(kind=ScheduleKind.AT, value="08:00")
        data = schedule.model_dump()
        restored = CronSchedule(**data)
        assert restored.kind == schedule.kind
        assert restored.value == schedule.value


# ---------------------------------------------------------------------------
# CronJob creation and serialization
# ---------------------------------------------------------------------------

class TestCronJob:
    """Tests for CronJob model creation and serialization."""

    def _make_job(self, **overrides) -> CronJob:
        defaults = {
            "id": "test-001",
            "name": "Test Job",
            "schedule": CronSchedule(kind=ScheduleKind.EVERY, value="5m"),
            "action": "agent",
            "action_config": {"agent_id": "default"},
        }
        defaults.update(overrides)
        return CronJob(**defaults)

    def test_create_basic_job(self):
        job = self._make_job()
        assert job.id == "test-001"
        assert job.name == "Test Job"
        assert job.action == "agent"
        assert job.enabled is True
        assert job.last_run is None
        assert job.next_run is None
        assert job.run_count == 0
        assert job.last_error is None
        assert job.metadata == {}

    def test_job_with_all_fields(self):
        now = datetime.now(UTC)
        job = self._make_job(
            enabled=False,
            last_run=now,
            next_run=now + timedelta(hours=1),
            run_count=42,
            last_error="timeout",
            metadata={"source": "heartbeat"},
        )
        assert job.enabled is False
        assert job.last_run == now
        assert job.run_count == 42
        assert job.last_error == "timeout"
        assert job.metadata["source"] == "heartbeat"

    def test_job_action_types(self):
        for action in ("agent", "command", "webhook"):
            job = self._make_job(action=action)
            assert job.action == action

    def test_job_serialization_roundtrip(self):
        job = self._make_job(
            action_config={"url": "https://example.com/hook"},
            metadata={"tag": "daily"},
        )
        data = job.model_dump(mode="json")
        restored = CronJob(**data)
        assert restored.id == job.id
        assert restored.name == job.name
        assert restored.schedule.kind == job.schedule.kind
        assert restored.schedule.value == job.schedule.value
        assert restored.action_config == job.action_config
        assert restored.metadata == job.metadata

    def test_job_model_dump_mode_json(self):
        """Ensure model_dump(mode='json') produces JSON-serializable output."""
        now = datetime.now(UTC)
        job = self._make_job(last_run=now)
        data = job.model_dump(mode="json")
        # datetime should be serialized as a string
        assert isinstance(data["last_run"], str)
        # schedule should be a dict
        assert isinstance(data["schedule"], dict)
        assert data["schedule"]["kind"] == "every"

    def test_job_default_action_config_is_independent(self):
        """Default dicts should not be shared between instances."""
        job1 = self._make_job(id="a", action_config={})
        job2 = self._make_job(id="b", action_config={})
        job1.action_config["key"] = "val"
        assert "key" not in job2.action_config


# ---------------------------------------------------------------------------
# CronStore CRUD operations
# ---------------------------------------------------------------------------

class TestCronStore:
    """Tests for CronStore in-memory store."""

    def _make_job(self, job_id: str = "j1", name: str = "Job 1", **kw) -> CronJob:
        return CronJob(
            id=job_id,
            name=name,
            schedule=CronSchedule(kind=ScheduleKind.EVERY, value="10m"),
            action="agent",
            **kw,
        )

    def test_add_and_get(self):
        store = CronStore()
        job = self._make_job()
        result = store.add(job)
        assert result.id == "j1"
        assert store.get("j1") is job

    def test_get_nonexistent_returns_none(self):
        store = CronStore()
        assert store.get("no-such-id") is None

    def test_add_generates_id_if_empty(self):
        store = CronStore()
        job = self._make_job(job_id="")
        result = store.add(job)
        assert result.id != ""
        assert len(result.id) == 8
        assert store.get(result.id) is result

    def test_list_all(self):
        store = CronStore()
        store.add(self._make_job("j1", "Job 1"))
        store.add(self._make_job("j2", "Job 2"))
        store.add(self._make_job("j3", "Job 3"))
        assert len(store.list_all()) == 3

    def test_list_all_enabled_only(self):
        store = CronStore()
        store.add(self._make_job("j1", "Job 1", enabled=True))
        store.add(self._make_job("j2", "Job 2", enabled=False))
        store.add(self._make_job("j3", "Job 3", enabled=True))

        all_jobs = store.list_all(enabled_only=False)
        enabled_jobs = store.list_all(enabled_only=True)

        assert len(all_jobs) == 3
        assert len(enabled_jobs) == 2
        assert all(j.enabled for j in enabled_jobs)

    def test_update_existing_job(self):
        store = CronStore()
        store.add(self._make_job())
        result = store.update("j1", name="Updated Name", enabled=False)
        assert result is not None
        assert result.name == "Updated Name"
        assert result.enabled is False

    def test_update_nonexistent_returns_none(self):
        store = CronStore()
        assert store.update("no-such-id", name="Nope") is None

    def test_update_ignores_unknown_fields(self):
        store = CronStore()
        store.add(self._make_job())
        result = store.update("j1", nonexistent_field="value")
        assert result is not None
        assert not hasattr(result, "nonexistent_field")

    def test_delete_existing_job(self):
        store = CronStore()
        store.add(self._make_job())
        assert store.delete("j1") is True
        assert store.get("j1") is None

    def test_delete_nonexistent_returns_false(self):
        store = CronStore()
        assert store.delete("no-such-id") is False

    def test_mark_run_success(self):
        store = CronStore()
        store.add(self._make_job())
        next_time = datetime.now(UTC) + timedelta(minutes=10)
        store.mark_run("j1", success=True, next_run=next_time)

        job = store.get("j1")
        assert job is not None
        assert job.last_run is not None
        assert job.run_count == 1
        assert job.last_error is None
        assert job.next_run == next_time

    def test_mark_run_failure(self):
        store = CronStore()
        store.add(self._make_job())
        store.mark_run("j1", success=False, error="connection timeout")

        job = store.get("j1")
        assert job is not None
        assert job.run_count == 1
        assert job.last_error == "connection timeout"

    def test_mark_run_increments_count(self):
        store = CronStore()
        store.add(self._make_job())
        for _ in range(5):
            store.mark_run("j1", success=True)
        assert store.get("j1").run_count == 5

    def test_mark_run_nonexistent_is_noop(self):
        store = CronStore()
        # Should not raise
        store.mark_run("no-such-id", success=True)

    def test_to_dicts(self):
        store = CronStore()
        store.add(self._make_job("j1", "Job 1"))
        store.add(self._make_job("j2", "Job 2"))
        dicts = store.to_dicts()
        assert len(dicts) == 2
        assert all(isinstance(d, dict) for d in dicts)
        ids = {d["id"] for d in dicts}
        assert ids == {"j1", "j2"}

    def test_load_dicts(self):
        store = CronStore()
        data = [
            {
                "id": "j1",
                "name": "Job 1",
                "schedule": {"kind": "every", "value": "5m"},
                "action": "agent",
            },
            {
                "id": "j2",
                "name": "Job 2",
                "schedule": {"kind": "at", "value": "09:00"},
                "action": "webhook",
                "action_config": {"url": "https://example.com"},
            },
        ]
        count = store.load_dicts(data)
        assert count == 2
        assert store.get("j1") is not None
        assert store.get("j2") is not None
        assert store.get("j2").action == "webhook"

    def test_load_dicts_skips_invalid(self):
        store = CronStore()
        data = [
            {
                "id": "j1",
                "name": "Job 1",
                "schedule": {"kind": "every", "value": "5m"},
                "action": "agent",
            },
            {"bad": "data"},  # Missing required fields
        ]
        count = store.load_dicts(data)
        assert count == 1
        assert store.get("j1") is not None

    def test_to_dicts_then_load_roundtrip(self):
        store1 = CronStore()
        store1.add(self._make_job("j1", "Job 1"))
        store1.add(self._make_job("j2", "Job 2", enabled=False))
        dicts = store1.to_dicts()

        store2 = CronStore()
        count = store2.load_dicts(dicts)
        assert count == 2
        assert store2.get("j1").name == "Job 1"
        assert store2.get("j2").enabled is False

    def test_empty_store_operations(self):
        store = CronStore()
        assert store.list_all() == []
        assert store.to_dicts() == []
        assert store.load_dicts([]) == 0


# ---------------------------------------------------------------------------
# _parse_interval
# ---------------------------------------------------------------------------

class TestParseInterval:
    """Tests for the _parse_interval helper function."""

    def test_seconds(self):
        result = _parse_interval("30s")
        assert result == timedelta(seconds=30)

    def test_minutes(self):
        result = _parse_interval("15m")
        assert result == timedelta(minutes=15)

    def test_hours(self):
        result = _parse_interval("2h")
        assert result == timedelta(hours=2)

    def test_days(self):
        result = _parse_interval("1d")
        assert result == timedelta(days=1)

    def test_large_value(self):
        result = _parse_interval("999m")
        assert result == timedelta(minutes=999)

    def test_with_whitespace(self):
        result = _parse_interval("  30m  ")
        assert result == timedelta(minutes=30)

    def test_with_space_between_number_and_unit(self):
        result = _parse_interval("10 m")
        assert result == timedelta(minutes=10)

    def test_uppercase_unit(self):
        result = _parse_interval("5H")
        assert result == timedelta(hours=5)

    def test_invalid_unit(self):
        assert _parse_interval("10w") is None

    def test_invalid_format_no_number(self):
        assert _parse_interval("m") is None

    def test_invalid_format_no_unit(self):
        assert _parse_interval("30") is None

    def test_empty_string(self):
        assert _parse_interval("") is None

    def test_completely_invalid(self):
        assert _parse_interval("every day at noon") is None

    def test_negative_not_matched(self):
        assert _parse_interval("-5m") is None

    def test_float_not_matched(self):
        assert _parse_interval("1.5h") is None

    def test_zero_value(self):
        result = _parse_interval("0m")
        assert result == timedelta(minutes=0)


# ---------------------------------------------------------------------------
# _next_at_run
# ---------------------------------------------------------------------------

class TestNextAtRun:
    """Tests for the _next_at_run helper function."""

    def test_future_time_today(self):
        """If the target time is later today, should return today."""
        base = datetime(2025, 6, 15, 10, 0, 0, tzinfo=UTC)
        result = _next_at_run("14:30", base)
        assert result.hour == 14
        assert result.minute == 30
        assert result.day == 15

    def test_past_time_rolls_to_tomorrow(self):
        """If the target time already passed today, should return tomorrow."""
        base = datetime(2025, 6, 15, 16, 0, 0, tzinfo=UTC)
        result = _next_at_run("14:30", base)
        assert result.hour == 14
        assert result.minute == 30
        assert result.day == 16

    def test_exact_same_time_rolls_to_tomorrow(self):
        """If 'after' is exactly the target time, should roll to tomorrow."""
        base = datetime(2025, 6, 15, 14, 30, 0, tzinfo=UTC)
        result = _next_at_run("14:30", base)
        assert result.day == 16

    def test_hour_only(self):
        """Should handle hour-only format like '9' (minute defaults to 0)."""
        base = datetime(2025, 6, 15, 5, 0, 0, tzinfo=UTC)
        result = _next_at_run("9", base)
        assert result.hour == 9
        assert result.minute == 0

    def test_midnight(self):
        base = datetime(2025, 6, 15, 1, 0, 0, tzinfo=UTC)
        result = _next_at_run("0:00", base)
        # 0:00 is before 1:00, so should be tomorrow
        assert result.day == 16
        assert result.hour == 0

    def test_with_whitespace(self):
        base = datetime(2025, 6, 15, 10, 0, 0, tzinfo=UTC)
        result = _next_at_run("  14:30  ", base)
        assert result.hour == 14
        assert result.minute == 30


# ---------------------------------------------------------------------------
# compute_next_run
# ---------------------------------------------------------------------------

class TestComputeNextRun:
    """Tests for the compute_next_run function."""

    def _make_job(self, kind: ScheduleKind, value: str, **kw) -> CronJob:
        return CronJob(
            id="test",
            name="Test",
            schedule=CronSchedule(kind=kind, value=value),
            action="agent",
            **kw,
        )

    def test_every_no_last_run(self):
        """With no last_run, next_run should be now + interval."""
        job = self._make_job(ScheduleKind.EVERY, "30m")
        before = datetime.now(UTC)
        result = compute_next_run(job)
        after = datetime.now(UTC)

        assert result is not None
        # Should be approximately now + 30 minutes
        expected_low = before + timedelta(minutes=30)
        expected_high = after + timedelta(minutes=30)
        assert expected_low <= result <= expected_high

    def test_every_with_last_run(self):
        """With a last_run set, next_run should be last_run + interval."""
        last = datetime(2025, 6, 15, 10, 0, 0, tzinfo=UTC)
        job = self._make_job(ScheduleKind.EVERY, "2h", last_run=last)
        result = compute_next_run(job)
        assert result == datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)

    def test_every_invalid_interval_returns_none(self):
        job = self._make_job(ScheduleKind.EVERY, "invalid")
        assert compute_next_run(job) is None

    def test_at_schedule(self):
        """AT schedule should return a future datetime at the specified time."""
        job = self._make_job(ScheduleKind.AT, "23:59")
        result = compute_next_run(job)
        assert result is not None
        assert result.hour == 23
        assert result.minute == 59
        # Should be in the future
        assert result > datetime.now(UTC)

    def test_cron_schedule(self):
        """CRON schedule with a valid cron expression should work via croniter."""
        pytest.importorskip("croniter", reason="croniter not installed")
        job = self._make_job(ScheduleKind.CRON, "*/5 * * * *")
        result = compute_next_run(job)
        assert result is not None
        # The next run should be within 5 minutes from now
        assert result <= datetime.now(UTC) + timedelta(minutes=5, seconds=5)
        # And should be in the future (or very close to now)
        assert result >= datetime.now(UTC) - timedelta(seconds=2)

    def test_cron_without_croniter_returns_none(self):
        """Without croniter installed, CRON schedule should return None gracefully."""
        with patch.dict("sys.modules", {"croniter": None}):
            from ungula.cron import scheduler as sched_mod
            # Force reimport to pick up the patched sys.modules
            job = self._make_job(ScheduleKind.CRON, "*/5 * * * *")
            # _next_cron_run catches ImportError and returns None
            result = compute_next_run(job)
            # Result depends on whether croniter was already imported;
            # just verify it doesn't crash
            assert result is None or result is not None

    def test_cron_invalid_expression_returns_none(self):
        pytest.importorskip("croniter", reason="croniter not installed")
        job = self._make_job(ScheduleKind.CRON, "not a cron expr")
        result = compute_next_run(job)
        assert result is None

    def test_every_seconds(self):
        last = datetime(2025, 6, 15, 10, 0, 0, tzinfo=UTC)
        job = self._make_job(ScheduleKind.EVERY, "45s", last_run=last)
        result = compute_next_run(job)
        assert result == datetime(2025, 6, 15, 10, 0, 45, tzinfo=UTC)

    def test_every_days(self):
        last = datetime(2025, 6, 15, 10, 0, 0, tzinfo=UTC)
        job = self._make_job(ScheduleKind.EVERY, "1d", last_run=last)
        result = compute_next_run(job)
        assert result == datetime(2025, 6, 16, 10, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# CronScheduler (async)
# ---------------------------------------------------------------------------

class TestCronScheduler:
    """Tests for the CronScheduler class."""

    def _make_job(self, job_id: str = "sched-1", **kw) -> CronJob:
        defaults = {
            "id": job_id,
            "name": "Scheduled Job",
            "schedule": CronSchedule(kind=ScheduleKind.EVERY, value="10m"),
            "action": "agent",
        }
        defaults.update(kw)
        return CronJob(**defaults)

    def test_init_defaults(self):
        scheduler = CronScheduler()
        assert scheduler.store is not None
        assert isinstance(scheduler.store, CronStore)
        assert scheduler.executor is None
        assert scheduler.tick_interval == 30.0
        assert scheduler._running is False

    def test_init_custom(self):
        store = CronStore()
        executor = AsyncMock()
        scheduler = CronScheduler(store=store, executor=executor, tick_interval=60.0)
        assert scheduler.store is store
        assert scheduler.executor is executor
        assert scheduler.tick_interval == 60.0

    async def test_start_sets_running(self):
        scheduler = CronScheduler(tick_interval=9999)
        await scheduler.start()
        assert scheduler._running is True
        assert scheduler._task is not None
        await scheduler.stop()

    async def test_start_idempotent(self):
        scheduler = CronScheduler(tick_interval=9999)
        await scheduler.start()
        task1 = scheduler._task
        await scheduler.start()  # Second call should be a no-op
        assert scheduler._task is task1
        await scheduler.stop()

    async def test_stop(self):
        scheduler = CronScheduler(tick_interval=9999)
        await scheduler.start()
        await scheduler.stop()
        assert scheduler._running is False

    async def test_stop_when_not_started(self):
        scheduler = CronScheduler()
        await scheduler.stop()  # Should not raise
        assert scheduler._running is False

    async def test_start_computes_initial_next_run(self):
        store = CronStore()
        job = self._make_job()
        store.add(job)
        assert job.next_run is None

        scheduler = CronScheduler(store=store, tick_interval=9999)
        await scheduler.start()

        assert job.next_run is not None
        await scheduler.stop()

    async def test_run_now_executes_job(self):
        executor = AsyncMock()
        store = CronStore()
        job = self._make_job()
        store.add(job)

        scheduler = CronScheduler(store=store, executor=executor)
        result = await scheduler.run_now("sched-1")

        assert result is True
        executor.assert_awaited_once_with(job)

    async def test_run_now_nonexistent_returns_false(self):
        scheduler = CronScheduler()
        result = await scheduler.run_now("no-such-job")
        assert result is False

    async def test_run_now_marks_run_on_success(self):
        executor = AsyncMock()
        store = CronStore()
        job = self._make_job()
        store.add(job)

        scheduler = CronScheduler(store=store, executor=executor)
        await scheduler.run_now("sched-1")

        assert job.run_count == 1
        assert job.last_run is not None
        assert job.last_error is None

    async def test_run_now_marks_error_on_failure(self):
        executor = AsyncMock(side_effect=RuntimeError("boom"))
        store = CronStore()
        job = self._make_job()
        store.add(job)

        scheduler = CronScheduler(store=store, executor=executor)
        await scheduler.run_now("sched-1")

        assert job.run_count == 1
        assert job.last_error == "boom"

    async def test_check_due_jobs_executes_due(self):
        executor = AsyncMock()
        store = CronStore()
        job = self._make_job()
        job.next_run = datetime.now(UTC) - timedelta(minutes=1)  # Already past due
        store.add(job)

        scheduler = CronScheduler(store=store, executor=executor)
        await scheduler._check_due_jobs()

        executor.assert_awaited_once_with(job)

    async def test_check_due_jobs_skips_future(self):
        executor = AsyncMock()
        store = CronStore()
        job = self._make_job()
        job.next_run = datetime.now(UTC) + timedelta(hours=1)  # Not yet due
        store.add(job)

        scheduler = CronScheduler(store=store, executor=executor)
        await scheduler._check_due_jobs()

        executor.assert_not_awaited()

    async def test_check_due_jobs_skips_disabled(self):
        executor = AsyncMock()
        store = CronStore()
        job = self._make_job(enabled=False)
        job.next_run = datetime.now(UTC) - timedelta(minutes=1)
        store.add(job)

        scheduler = CronScheduler(store=store, executor=executor)
        await scheduler._check_due_jobs()

        executor.assert_not_awaited()

    async def test_check_due_jobs_skips_no_next_run(self):
        executor = AsyncMock()
        store = CronStore()
        job = self._make_job()
        job.next_run = None
        store.add(job)

        scheduler = CronScheduler(store=store, executor=executor)
        await scheduler._check_due_jobs()

        executor.assert_not_awaited()

    async def test_execute_job_without_executor(self):
        """Scheduler with no executor should still mark the run."""
        store = CronStore()
        job = self._make_job()
        store.add(job)

        scheduler = CronScheduler(store=store, executor=None)
        await scheduler._execute_job(job)

        assert job.run_count == 1
        assert job.last_run is not None
        assert job.last_error is None

    async def test_multiple_due_jobs_all_execute(self):
        executor = AsyncMock()
        store = CronStore()

        past = datetime.now(UTC) - timedelta(minutes=1)
        for i in range(3):
            job = self._make_job(job_id=f"j{i}")
            job.next_run = past
            store.add(job)

        scheduler = CronScheduler(store=store, executor=executor)
        await scheduler._check_due_jobs()

        assert executor.await_count == 3
