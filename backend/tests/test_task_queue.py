"""
Tests for the task queue system.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from ungula.queue.manager import QueueManager
from ungula.queue.memory_backend import InMemoryBackend
from ungula.queue.types import Job, JobStatus, JobType
from ungula.queue.worker import QueueWorker


# --- Job model tests ---


class TestJobModel:
    """Tests for Job dataclass."""

    def test_defaults(self):
        job = Job()
        assert job.status == JobStatus.PENDING
        assert job.priority == 0
        assert job.retry_count == 0
        assert job.max_retries == 3
        assert job.id  # auto-generated

    def test_to_dict(self):
        job = Job(type=JobType.AGENT_RUN, payload={"key": "val"})
        d = job.to_dict()
        assert d["type"] == "agent_run"
        assert d["payload"] == {"key": "val"}
        assert d["status"] == "pending"
        assert "created_at" in d

    def test_job_type_enum(self):
        assert JobType.AGENT_RUN == "agent_run"
        assert JobType.CUSTOM == "custom"


# --- InMemoryBackend tests ---


class TestInMemoryBackend:
    """Tests for InMemoryBackend."""

    @pytest.mark.asyncio
    async def test_enqueue_and_dequeue(self):
        backend = InMemoryBackend()
        job = Job(type="test", payload={"x": 1})
        await backend.enqueue(job)

        dequeued = await backend.dequeue()
        assert dequeued is not None
        assert dequeued.id == job.id

    @pytest.mark.asyncio
    async def test_dequeue_empty(self):
        backend = InMemoryBackend()
        assert await backend.dequeue() is None

    @pytest.mark.asyncio
    async def test_priority_ordering(self):
        backend = InMemoryBackend()
        low = Job(type="test", priority=0)
        high = Job(type="test", priority=10)
        medium = Job(type="test", priority=5)

        await backend.enqueue(low)
        await backend.enqueue(high)
        await backend.enqueue(medium)

        first = await backend.dequeue()
        assert first.id == high.id

    @pytest.mark.asyncio
    async def test_get(self):
        backend = InMemoryBackend()
        job = Job(type="test")
        await backend.enqueue(job)

        found = await backend.get(job.id)
        assert found is not None
        assert found.id == job.id

        assert await backend.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_update(self):
        backend = InMemoryBackend()
        job = Job(type="test")
        await backend.enqueue(job)

        job.status = JobStatus.RUNNING
        await backend.update(job)

        updated = await backend.get(job.id)
        assert updated.status == JobStatus.RUNNING

    @pytest.mark.asyncio
    async def test_list_jobs_filter_status(self):
        backend = InMemoryBackend()
        j1 = Job(type="test", status=JobStatus.PENDING)
        j2 = Job(type="test", status=JobStatus.COMPLETED)
        await backend.enqueue(j1)
        await backend.enqueue(j2)

        pending = await backend.list_jobs(status=JobStatus.PENDING)
        assert len(pending) == 1
        assert pending[0].id == j1.id

    @pytest.mark.asyncio
    async def test_list_jobs_filter_type(self):
        backend = InMemoryBackend()
        j1 = Job(type="agent_run")
        j2 = Job(type="custom")
        await backend.enqueue(j1)
        await backend.enqueue(j2)

        results = await backend.list_jobs(job_type="agent_run")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_delete(self):
        backend = InMemoryBackend()
        job = Job(type="test")
        await backend.enqueue(job)
        assert await backend.delete(job.id) is True
        assert await backend.delete(job.id) is False
        assert await backend.get(job.id) is None

    @pytest.mark.asyncio
    async def test_cleanup(self):
        backend = InMemoryBackend()

        old_job = Job(type="test", status=JobStatus.COMPLETED)
        old_job.created_at = datetime.now(UTC) - timedelta(days=10)
        await backend.enqueue(old_job)

        recent_job = Job(type="test", status=JobStatus.COMPLETED)
        await backend.enqueue(recent_job)

        pending_old = Job(type="test", status=JobStatus.PENDING)
        pending_old.created_at = datetime.now(UTC) - timedelta(days=10)
        await backend.enqueue(pending_old)

        removed = await backend.cleanup(max_age_days=7)
        assert removed == 1  # Only old completed job

    @pytest.mark.asyncio
    async def test_ping(self):
        backend = InMemoryBackend()
        assert await backend.ping() is True


# --- QueueWorker tests ---


class TestQueueWorker:
    """Tests for QueueWorker."""

    @pytest.mark.asyncio
    async def test_process_job(self):
        """Worker processes a job and marks it completed."""
        backend = InMemoryBackend()
        worker = QueueWorker(backend=backend, poll_interval=0.1)

        handler = AsyncMock(return_value={"result": "ok"})
        worker.register_handler("test", handler)

        job = Job(type="test", payload={"x": 1})
        await backend.enqueue(job)

        await worker.start()
        await asyncio.sleep(0.3)
        await worker.stop()

        updated = await backend.get(job.id)
        assert updated.status == JobStatus.COMPLETED
        assert updated.result == {"result": "ok"}
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Worker retries failed jobs up to max_retries."""
        backend = InMemoryBackend()
        worker = QueueWorker(backend=backend, poll_interval=0.1)

        call_count = 0

        async def flaky_handler(job):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("transient error")
            return {"ok": True}

        worker.register_handler("test", flaky_handler)

        job = Job(type="test", max_retries=3)
        await backend.enqueue(job)

        await worker.start()
        await asyncio.sleep(1.0)
        await worker.stop()

        updated = await backend.get(job.id)
        assert updated.status == JobStatus.COMPLETED
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """Job permanently fails after max_retries."""
        backend = InMemoryBackend()
        worker = QueueWorker(backend=backend, poll_interval=0.1)

        handler = AsyncMock(side_effect=ValueError("always fails"))
        worker.register_handler("test", handler)

        job = Job(type="test", max_retries=2)
        await backend.enqueue(job)

        await worker.start()
        await asyncio.sleep(1.0)
        await worker.stop()

        updated = await backend.get(job.id)
        assert updated.status == JobStatus.FAILED
        assert updated.error == "always fails"

    @pytest.mark.asyncio
    async def test_no_handler(self):
        """Jobs with no handler are marked failed."""
        backend = InMemoryBackend()
        worker = QueueWorker(backend=backend, poll_interval=0.1)

        job = Job(type="unknown_type")
        await backend.enqueue(job)

        await worker.start()
        await asyncio.sleep(0.3)
        await worker.stop()

        updated = await backend.get(job.id)
        assert updated.status == JobStatus.FAILED
        assert "No handler" in updated.error


# --- QueueManager tests ---


class TestQueueManager:
    """Tests for QueueManager."""

    @pytest.mark.asyncio
    async def test_initialize_memory_fallback(self):
        """Without Redis config, falls back to in-memory."""
        qm = QueueManager()
        backend_type = await qm.initialize()
        assert backend_type == "memory"
        assert isinstance(qm.backend, InMemoryBackend)

    @pytest.mark.asyncio
    async def test_submit_and_get(self):
        qm = QueueManager()
        await qm.initialize()

        job = await qm.submit(
            job_type="test",
            payload={"key": "val"},
            priority=5,
        )
        assert job.type == "test"
        assert job.priority == 5

        retrieved = await qm.get_job(job.id)
        assert retrieved is not None
        assert retrieved.id == job.id

    @pytest.mark.asyncio
    async def test_cancel(self):
        qm = QueueManager()
        await qm.initialize()

        job = await qm.submit(job_type="test", payload={})
        assert await qm.cancel(job.id) is True

        updated = await qm.get_job(job.id)
        assert updated.status == JobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_non_pending(self):
        qm = QueueManager()
        await qm.initialize()

        job = await qm.submit(job_type="test", payload={})
        job.status = JobStatus.RUNNING
        await qm.backend.update(job)

        assert await qm.cancel(job.id) is False

    @pytest.mark.asyncio
    async def test_status(self):
        qm = QueueManager()
        await qm.initialize()

        await qm.submit(job_type="test", payload={})
        await qm.submit(job_type="test", payload={})

        status = await qm.status()
        assert status["backend"] == "memory"
        assert status["total_jobs"] == 2

    @pytest.mark.asyncio
    async def test_list_jobs(self):
        qm = QueueManager()
        await qm.initialize()

        await qm.submit(job_type="a", payload={})
        await qm.submit(job_type="b", payload={})

        all_jobs = await qm.list_jobs()
        assert len(all_jobs) == 2

        a_jobs = await qm.list_jobs(job_type="a")
        assert len(a_jobs) == 1

    @pytest.mark.asyncio
    async def test_cleanup(self):
        qm = QueueManager()
        await qm.initialize()

        job = await qm.submit(job_type="test", payload={})
        job.status = JobStatus.COMPLETED
        job.created_at = datetime.now(UTC) - timedelta(days=10)
        await qm.backend.update(job)

        removed = await qm.cleanup(max_age_days=7)
        assert removed == 1
