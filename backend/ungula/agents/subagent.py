"""
Subagent management system.

Allows the main agent to spawn child conversations (subagents)
for parallel task execution. Each subagent gets its own conversation
context and can run independently.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class SubagentStatus(str, Enum):
    """Status of a subagent session."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class SubagentSession:
    """Tracks the lifecycle of a spawned subagent."""

    id: UUID = field(default_factory=uuid4)
    parent_conversation_id: UUID | None = None
    conversation_id: UUID | None = None
    task_description: str = ""
    status: SubagentStatus = SubagentStatus.PENDING
    result: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "id": str(self.id),
            "parent_conversation_id": str(self.parent_conversation_id) if self.parent_conversation_id else None,
            "conversation_id": str(self.conversation_id) if self.conversation_id else None,
            "task_description": self.task_description,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class SubagentManager:
    """
    Manages spawning and tracking of subagent sessions.

    Subagents run as independent conversations with their own
    context. The parent agent can check status and collect results.
    """

    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self._sessions: dict[UUID, SubagentSession] = {}
        self._tasks: dict[UUID, asyncio.Task] = {}

    async def spawn(
        self,
        task_description: str,
        parent_conversation_id: UUID | None = None,
        agent_runner: Any = None,
        storage: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> SubagentSession:
        """
        Spawn a new subagent.

        Creates a new conversation and runs the task asynchronously.

        Args:
            task_description: What the subagent should do.
            parent_conversation_id: The parent conversation.
            agent_runner: The AgentRunner instance.
            storage: The storage backend.
            metadata: Optional metadata.

        Returns:
            The SubagentSession for tracking.
        """
        # Check concurrent limit
        active = sum(
            1 for s in self._sessions.values()
            if s.status == SubagentStatus.RUNNING
        )
        if active >= self.max_concurrent:
            raise RuntimeError(
                f"Max concurrent subagents ({self.max_concurrent}) reached"
            )

        session = SubagentSession(
            parent_conversation_id=parent_conversation_id,
            task_description=task_description,
            metadata=metadata or {},
        )
        self._sessions[session.id] = session

        # Create a new conversation for the subagent
        if storage:
            from ..storage.base import ConversationCreate

            conv = await storage.create_conversation(
                ConversationCreate(
                    title=f"Subagent: {task_description[:50]}",
                    metadata={
                        "subagent_id": str(session.id),
                        "parent_conversation_id": str(parent_conversation_id) if parent_conversation_id else None,
                    },
                )
            )
            session.conversation_id = conv.id

        # Run asynchronously
        if agent_runner and session.conversation_id:
            task = asyncio.create_task(
                self._run_subagent(session, agent_runner)
            )
            self._tasks[session.id] = task

        logger.info("Spawned subagent %s: %s", session.id, task_description[:60])
        return session

    async def get_session(self, session_id: UUID) -> SubagentSession | None:
        """Get a subagent session by ID."""
        return self._sessions.get(session_id)

    async def list_sessions(
        self,
        parent_id: UUID | None = None,
        status: SubagentStatus | None = None,
    ) -> list[SubagentSession]:
        """List subagent sessions with optional filtering."""
        sessions = list(self._sessions.values())

        if parent_id:
            sessions = [s for s in sessions if s.parent_conversation_id == parent_id]
        if status:
            sessions = [s for s in sessions if s.status == status]

        return sorted(sessions, key=lambda s: s.created_at, reverse=True)

    async def cancel(self, session_id: UUID) -> bool:
        """Cancel a running subagent."""
        session = self._sessions.get(session_id)
        if not session:
            return False

        task = self._tasks.get(session_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        session.status = SubagentStatus.CANCELLED
        session.completed_at = datetime.now(UTC)
        logger.info("Cancelled subagent %s", session_id)
        return True

    async def collect_result(self, session_id: UUID) -> str | None:
        """Wait for and collect a subagent's result."""
        session = self._sessions.get(session_id)
        if not session:
            return None

        task = self._tasks.get(session_id)
        if task and not task.done():
            try:
                await asyncio.wait_for(task, timeout=300)
            except asyncio.TimeoutError:
                session.status = SubagentStatus.FAILED
                session.error = "Timed out waiting for result"
            except asyncio.CancelledError:
                pass

        return session.result

    async def _run_subagent(
        self,
        session: SubagentSession,
        agent_runner: Any,
    ) -> None:
        """Execute the subagent's task."""
        session.status = SubagentStatus.RUNNING
        session.started_at = datetime.now(UTC)

        try:
            response = await agent_runner.run(
                conversation_id=session.conversation_id,
                user_message=session.task_description,
            )

            session.result = response.content
            session.status = SubagentStatus.COMPLETED
            session.completed_at = datetime.now(UTC)

            logger.info(
                "Subagent %s completed (result: %d chars)",
                session.id,
                len(session.result or ""),
            )

        except asyncio.CancelledError:
            session.status = SubagentStatus.CANCELLED
            session.completed_at = datetime.now(UTC)
            raise

        except Exception as e:
            session.status = SubagentStatus.FAILED
            session.error = str(e)
            session.completed_at = datetime.now(UTC)
            logger.error("Subagent %s failed: %s", session.id, e)
