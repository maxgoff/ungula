"""
SQLite storage backend implementation for Ungula.
"""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import bcrypt

from typing import Any

from .base import (
    AgentRecord,
    AgentRecordCreate,
    Conversation,
    ConversationCreate,
    InboxMessage,
    InboxMessageCreate,
    MemoryEntry,
    MemoryEntryCreate,
    Message,
    MessageCreate,
    Session,
    SessionCreate,
    StorageBackend,
    Task,
    TaskCreate,
    TokenUsage,
    TokenUsageCreate,
    User,
    UserCreate,
    UserInDB,
)
from .models import (
    AgentModel,
    Base,
    ConversationModel,
    InboxMessageModel,
    MemoryModel,
    MessageModel,
    SessionModel,
    TaskModel,
    TokenUsageModel,
    UserModel,
)


class SQLiteStorage(StorageBackend):
    """SQLite implementation of the storage backend."""

    def __init__(self, db_path: Path | str):
        """
        Initialize SQLite storage.

        Args:
            db_path: Path to the SQLite database file.
        """
        if isinstance(db_path, str):
            db_path = Path(db_path)

        # Ensure parent directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self.db_path = db_path
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            echo=False,
        )
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def initialize(self) -> None:
        """Create all tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        """Close the database connection."""
        await self.engine.dispose()

    def _session(self) -> AsyncSession:
        """Get a new session."""
        return self.session_factory()

    def session(self) -> AsyncSession:
        """Get a new async session (public API for subsystems like NodeManager)."""
        return self.session_factory()

    # Users

    async def create_user(self, data: UserCreate) -> User:
        """Create a new user."""
        async with self._session() as session:
            hashed_password = bcrypt.hashpw(
                data.password.encode("utf-8"),
                bcrypt.gensalt(),
            ).decode("utf-8")
            model = UserModel(
                email=data.email,
                hashed_password=hashed_password,
                name=data.name,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return self._user_from_model(model)

    async def get_user(self, user_id: UUID) -> User | None:
        """Get a user by ID."""
        async with self._session() as session:
            result = await session.execute(
                select(UserModel).where(UserModel.id == str(user_id))
            )
            model = result.scalar_one_or_none()
            if model:
                return self._user_from_model(model)
            return None

    async def get_user_by_email(self, email: str) -> UserInDB | None:
        """Get a user by email (includes hashed password)."""
        async with self._session() as session:
            result = await session.execute(
                select(UserModel).where(UserModel.email == email)
            )
            model = result.scalar_one_or_none()
            if model:
                return self._user_in_db_from_model(model)
            return None

    async def update_user(
        self, user_id: UUID, name: str | None = None, is_active: bool | None = None
    ) -> User | None:
        """Update user details."""
        async with self._session() as session:
            result = await session.execute(
                select(UserModel).where(UserModel.id == str(user_id))
            )
            model = result.scalar_one_or_none()
            if not model:
                return None

            if name is not None:
                model.name = name
            if is_active is not None:
                model.is_active = is_active

            await session.commit()
            await session.refresh(model)
            return self._user_from_model(model)

    def _user_from_model(self, model: UserModel) -> User:
        """Convert SQLAlchemy model to Pydantic User model."""
        return User(
            id=UUID(model.id),
            email=model.email,
            name=model.name,
            is_active=model.is_active,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def _user_in_db_from_model(self, model: UserModel) -> UserInDB:
        """Convert SQLAlchemy model to Pydantic UserInDB model."""
        return UserInDB(
            id=UUID(model.id),
            email=model.email,
            name=model.name,
            is_active=model.is_active,
            hashed_password=model.hashed_password,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    # Conversations

    async def create_conversation(self, data: ConversationCreate) -> Conversation:
        """Create a new conversation."""
        async with self._session() as session:
            model = ConversationModel(
                user_id=str(data.user_id) if data.user_id else None,
                title=data.title,
                metadata_json=data.metadata,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return self._conversation_from_model(model)

    async def get_conversation(self, conversation_id: UUID) -> Conversation | None:
        """Get a conversation by ID."""
        async with self._session() as session:
            result = await session.execute(
                select(ConversationModel).where(
                    ConversationModel.id == str(conversation_id)
                )
            )
            model = result.scalar_one_or_none()
            if model:
                return self._conversation_from_model(model)
            return None

    async def list_conversations(
        self, user_id: UUID | None = None, limit: int = 50, offset: int = 0
    ) -> list[Conversation]:
        """List conversations with optional user filtering and pagination."""
        async with self._session() as session:
            query = select(ConversationModel)
            if user_id:
                query = query.where(ConversationModel.user_id == str(user_id))
            query = (
                query.order_by(ConversationModel.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(query)
            models = result.scalars().all()
            return [self._conversation_from_model(m) for m in models]

    async def update_conversation(
        self,
        conversation_id: UUID,
        title: str | None = None,
        metadata: dict | None = None,
    ) -> Conversation | None:
        """Update conversation title and/or metadata."""
        async with self._session() as session:
            result = await session.execute(
                select(ConversationModel).where(
                    ConversationModel.id == str(conversation_id)
                )
            )
            model = result.scalar_one_or_none()
            if not model:
                return None
            if title is not None:
                model.title = title
            if metadata is not None:
                model.metadata_json = metadata
            model.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(model)
            return self._conversation_from_model(model)

    async def delete_conversation(self, conversation_id: UUID) -> bool:
        """Delete a conversation and its messages."""
        async with self._session() as session:
            result = await session.execute(
                select(ConversationModel).where(
                    ConversationModel.id == str(conversation_id)
                )
            )
            model = result.scalar_one_or_none()
            if model:
                await session.delete(model)
                await session.commit()
                return True
            return False

    async def count_messages_batch(
        self, conversation_ids: list[UUID]
    ) -> dict[UUID, int]:
        """Count messages for multiple conversations in a single query."""
        if not conversation_ids:
            return {}
        from sqlalchemy import func as sql_func

        async with self._session() as session:
            str_ids = [str(cid) for cid in conversation_ids]
            result = await session.execute(
                select(
                    MessageModel.conversation_id,
                    sql_func.count(MessageModel.id),
                )
                .where(MessageModel.conversation_id.in_(str_ids))
                .group_by(MessageModel.conversation_id)
            )
            counts: dict[UUID, int] = {}
            for conv_id_str, count in result.all():
                counts[UUID(conv_id_str)] = count
            # Fill in zeros for conversations with no messages
            for cid in conversation_ids:
                if cid not in counts:
                    counts[cid] = 0
            return counts

    def _conversation_from_model(self, model: ConversationModel) -> Conversation:
        """Convert SQLAlchemy model to Pydantic model."""
        return Conversation(
            id=UUID(model.id),
            user_id=UUID(model.user_id) if model.user_id else None,
            title=model.title,
            created_at=model.created_at,
            updated_at=model.updated_at,
            metadata=model.metadata_json,
        )

    # Messages

    async def create_message(self, data: MessageCreate) -> Message:
        """Create a new message."""
        async with self._session() as session:
            model = MessageModel(
                conversation_id=str(data.conversation_id),
                role=data.role,
                content=data.content,
                agent_id=data.agent_id,
                model=data.model,
                stage1_json=data.stage1,
                stage2_json=data.stage2,
                stage3_json=data.stage3,
                metadata_json=data.metadata,
            )
            session.add(model)

            # Update conversation updated_at
            conv_result = await session.execute(
                select(ConversationModel).where(
                    ConversationModel.id == str(data.conversation_id)
                )
            )
            conv = conv_result.scalar_one_or_none()
            if conv:
                conv.updated_at = datetime.now(UTC)

            await session.commit()
            await session.refresh(model)
            return self._message_from_model(model)

    async def get_message(self, message_id: UUID) -> Message | None:
        """Get a message by ID."""
        async with self._session() as session:
            result = await session.execute(
                select(MessageModel).where(MessageModel.id == str(message_id))
            )
            model = result.scalar_one_or_none()
            if model:
                return self._message_from_model(model)
            return None

    async def list_messages(
        self, conversation_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Message]:
        """List messages in a conversation."""
        async with self._session() as session:
            result = await session.execute(
                select(MessageModel)
                .where(MessageModel.conversation_id == str(conversation_id))
                .order_by(MessageModel.created_at.asc())
                .limit(limit)
                .offset(offset)
            )
            models = result.scalars().all()
            return [self._message_from_model(m) for m in models]

    def _message_from_model(self, model: MessageModel) -> Message:
        """Convert SQLAlchemy model to Pydantic model."""
        return Message(
            id=UUID(model.id),
            conversation_id=UUID(model.conversation_id),
            role=model.role,
            content=model.content,
            agent_id=model.agent_id,
            model=model.model,
            stage1=model.stage1_json,
            stage2=model.stage2_json,
            stage3=model.stage3_json,
            created_at=model.created_at,
            metadata=model.metadata_json,
        )

    # Tasks

    async def create_task(self, data: TaskCreate) -> Task:
        """Create a new task."""
        async with self._session() as session:
            model = TaskModel(
                title=data.title,
                description=data.description,
                agent_id=data.agent_id,
                parent_task_id=str(data.parent_task_id) if data.parent_task_id else None,
                priority=data.priority,
                metadata_json=data.metadata,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return self._task_from_model(model)

    async def get_task(self, task_id: UUID) -> Task | None:
        """Get a task by ID."""
        async with self._session() as session:
            result = await session.execute(
                select(TaskModel).where(TaskModel.id == str(task_id))
            )
            model = result.scalar_one_or_none()
            if model:
                return self._task_from_model(model)
            return None

    async def list_tasks(
        self,
        status: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Task]:
        """List tasks with optional filtering."""
        async with self._session() as session:
            query = select(TaskModel)
            if status:
                query = query.where(TaskModel.status == status)
            if agent_id:
                query = query.where(TaskModel.agent_id == agent_id)
            query = (
                query.order_by(TaskModel.priority.desc(), TaskModel.created_at.asc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(query)
            models = result.scalars().all()
            return [self._task_from_model(m) for m in models]

    async def update_task_status(
        self,
        task_id: UUID,
        status: str,
        result: str | None = None,
        error: str | None = None,
        blocked_reason: str | None = None,
    ) -> Task | None:
        """Update task status."""
        async with self._session() as session:
            query_result = await session.execute(
                select(TaskModel).where(TaskModel.id == str(task_id))
            )
            model = query_result.scalar_one_or_none()
            if not model:
                return None

            model.status = status
            if result is not None:
                model.result = result
            if error is not None:
                model.error = error
            if blocked_reason is not None:
                model.blocked_reason = blocked_reason

            # Update timestamps based on status
            now = datetime.now(UTC)
            if status == "running" and model.started_at is None:
                model.started_at = now
            elif status in ("completed", "failed", "cancelled"):
                model.completed_at = now

            await session.commit()
            await session.refresh(model)
            return self._task_from_model(model)

    def _task_from_model(self, model: TaskModel) -> Task:
        """Convert SQLAlchemy model to Pydantic model."""
        return Task(
            id=UUID(model.id),
            title=model.title,
            description=model.description,
            status=model.status,
            agent_id=model.agent_id,
            parent_task_id=UUID(model.parent_task_id) if model.parent_task_id else None,
            priority=model.priority,
            result=model.result,
            error=model.error,
            blocked_reason=model.blocked_reason,
            created_at=model.created_at,
            started_at=model.started_at,
            completed_at=model.completed_at,
            metadata=model.metadata_json,
        )

    # Agents

    async def create_agent(self, data: AgentRecordCreate) -> AgentRecord:
        """Create or update an agent record."""
        async with self._session() as session:
            result = await session.execute(
                select(AgentModel).where(AgentModel.id == data.id)
            )
            model = result.scalar_one_or_none()

            if model:
                # Update existing
                model.name = data.name
                model.type = data.type
                model.config_json = data.config
            else:
                # Create new
                model = AgentModel(
                    id=data.id,
                    name=data.name,
                    type=data.type,
                    config_json=data.config,
                )
                session.add(model)

            await session.commit()
            await session.refresh(model)
            return self._agent_from_model(model)

    async def get_agent(self, agent_id: str) -> AgentRecord | None:
        """Get an agent by ID."""
        async with self._session() as session:
            result = await session.execute(
                select(AgentModel).where(AgentModel.id == agent_id)
            )
            model = result.scalar_one_or_none()
            if model:
                return self._agent_from_model(model)
            return None

    async def list_agents(self) -> list[AgentRecord]:
        """List all agents."""
        async with self._session() as session:
            result = await session.execute(
                select(AgentModel).order_by(AgentModel.name)
            )
            models = result.scalars().all()
            return [self._agent_from_model(m) for m in models]

    async def update_agent_status(
        self, agent_id: str, status: str
    ) -> AgentRecord | None:
        """Update agent status."""
        async with self._session() as session:
            result = await session.execute(
                select(AgentModel).where(AgentModel.id == agent_id)
            )
            model = result.scalar_one_or_none()
            if not model:
                return None

            model.status = status
            await session.commit()
            await session.refresh(model)
            return self._agent_from_model(model)

    async def update_agent_heartbeat(self, agent_id: str) -> AgentRecord | None:
        """Update agent last heartbeat time."""
        async with self._session() as session:
            result = await session.execute(
                select(AgentModel).where(AgentModel.id == agent_id)
            )
            model = result.scalar_one_or_none()
            if not model:
                return None

            model.last_heartbeat = datetime.now(UTC)
            await session.commit()
            await session.refresh(model)
            return self._agent_from_model(model)

    def _agent_from_model(self, model: AgentModel) -> AgentRecord:
        """Convert SQLAlchemy model to Pydantic model."""
        return AgentRecord(
            id=model.id,
            name=model.name,
            type=model.type,
            status=model.status,
            config=model.config_json,
            last_heartbeat=model.last_heartbeat,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    # Memory

    async def create_memory(self, data: MemoryEntryCreate) -> MemoryEntry:
        """Create a new memory entry."""
        async with self._session() as session:
            model = MemoryModel(
                content=data.content,
                memory_type=data.memory_type,
                level=data.level,
                project_id=data.project_id,
                agent_id=data.agent_id,
                source=data.source,
                embedding_json=data.embedding,
                metadata_json=data.metadata,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return self._memory_from_model(model)

    async def get_memory(self, memory_id: UUID) -> MemoryEntry | None:
        """Get a memory entry by ID."""
        async with self._session() as session:
            result = await session.execute(
                select(MemoryModel).where(MemoryModel.id == str(memory_id))
            )
            model = result.scalar_one_or_none()
            if model:
                # Update access tracking
                model.accessed_at = datetime.now(UTC)
                model.access_count += 1
                await session.commit()
                await session.refresh(model)
                return self._memory_from_model(model)
            return None

    async def search_memory(
        self,
        query_embedding: list[float] | None = None,
        memory_type: str | None = None,
        level: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        """
        Search memory entries.

        Note: For now, this does basic filtering. Vector similarity search
        will be handled by ChromaDB in the memory module.
        """
        async with self._session() as session:
            query = select(MemoryModel)

            if memory_type:
                query = query.where(MemoryModel.memory_type == memory_type)
            if level:
                query = query.where(MemoryModel.level == level)
            if project_id:
                query = query.where(MemoryModel.project_id == project_id)
            if agent_id:
                query = query.where(MemoryModel.agent_id == agent_id)

            query = query.order_by(MemoryModel.accessed_at.desc()).limit(limit)

            result = await session.execute(query)
            models = result.scalars().all()
            return [self._memory_from_model(m) for m in models]

    async def delete_memory(self, memory_id: UUID) -> bool:
        """Delete a memory entry."""
        async with self._session() as session:
            result = await session.execute(
                select(MemoryModel).where(MemoryModel.id == str(memory_id))
            )
            model = result.scalar_one_or_none()
            if model:
                await session.delete(model)
                await session.commit()
                return True
            return False

    def _memory_from_model(self, model: MemoryModel) -> MemoryEntry:
        """Convert SQLAlchemy model to Pydantic model."""
        return MemoryEntry(
            id=UUID(model.id),
            content=model.content,
            memory_type=model.memory_type,
            level=model.level,
            project_id=model.project_id,
            agent_id=model.agent_id,
            source=model.source,
            embedding=model.embedding_json,
            created_at=model.created_at,
            accessed_at=model.accessed_at,
            access_count=model.access_count,
            metadata=model.metadata_json,
        )

    # Sessions

    async def create_session(self, data: SessionCreate) -> Session:
        """Create a new session."""
        async with self._session() as session:
            model = SessionModel(
                channel=data.channel,
                contact_id=data.contact_id,
                contact_name=data.contact_name,
                conversation_id=str(data.conversation_id) if data.conversation_id else None,
                chat_type=data.chat_type,
                metadata_json=data.metadata,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return self._session_from_model(model)

    async def get_session(self, session_id: UUID) -> Session | None:
        """Get a session by ID."""
        async with self._session() as session:
            result = await session.execute(
                select(SessionModel).where(SessionModel.id == str(session_id))
            )
            model = result.scalar_one_or_none()
            if model:
                return self._session_from_model(model)
            return None

    async def get_session_by_contact(
        self, channel: str, contact_id: str
    ) -> Session | None:
        """Get a session by channel and contact ID."""
        async with self._session() as session:
            result = await session.execute(
                select(SessionModel).where(
                    SessionModel.channel == channel,
                    SessionModel.contact_id == contact_id,
                )
            )
            model = result.scalar_one_or_none()
            if model:
                return self._session_from_model(model)
            return None

    async def list_sessions(
        self,
        channel: str | None = None,
        active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Session]:
        """List sessions with optional filtering."""
        async with self._session() as session:
            query = select(SessionModel)
            if channel:
                query = query.where(SessionModel.channel == channel)
            if active is not None:
                query = query.where(SessionModel.active == active)
            query = (
                query.order_by(SessionModel.last_activity.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(query)
            models = result.scalars().all()
            return [self._session_from_model(m) for m in models]

    async def update_session(
        self,
        session_id: UUID,
        active: bool | None = None,
        conversation_id: UUID | None = None,
        contact_name: str | None = None,
    ) -> Session | None:
        """Update session details."""
        async with self._session() as session:
            result = await session.execute(
                select(SessionModel).where(SessionModel.id == str(session_id))
            )
            model = result.scalar_one_or_none()
            if not model:
                return None

            if active is not None:
                model.active = active
            if conversation_id is not None:
                model.conversation_id = str(conversation_id)
            if contact_name is not None:
                model.contact_name = contact_name

            await session.commit()
            await session.refresh(model)
            return self._session_from_model(model)

    async def update_session_activity(
        self, session_id: UUID, increment_count: bool = True
    ) -> Session | None:
        """Update session last activity and optionally increment message count."""
        async with self._session() as session:
            result = await session.execute(
                select(SessionModel).where(SessionModel.id == str(session_id))
            )
            model = result.scalar_one_or_none()
            if not model:
                return None

            model.last_activity = datetime.now(UTC)
            if increment_count:
                model.message_count += 1

            await session.commit()
            await session.refresh(model)
            return self._session_from_model(model)

    async def delete_session(self, session_id: UUID) -> bool:
        """Delete a session and its messages."""
        async with self._session() as session:
            result = await session.execute(
                select(SessionModel).where(SessionModel.id == str(session_id))
            )
            model = result.scalar_one_or_none()
            if model:
                await session.delete(model)
                await session.commit()
                return True
            return False

    def _session_from_model(self, model: SessionModel) -> Session:
        """Convert SQLAlchemy model to Pydantic model."""
        return Session(
            id=UUID(model.id),
            channel=model.channel,
            contact_id=model.contact_id,
            contact_name=model.contact_name,
            conversation_id=UUID(model.conversation_id) if model.conversation_id else None,
            chat_type=model.chat_type,
            active=model.active,
            last_activity=model.last_activity,
            message_count=model.message_count,
            created_at=model.created_at,
            metadata=model.metadata_json,
        )

    # Inbox Messages

    async def create_inbox_message(self, data: InboxMessageCreate) -> InboxMessage:
        """Create a new inbox message."""
        async with self._session() as session:
            model = InboxMessageModel(
                session_id=str(data.session_id),
                channel=data.channel,
                direction=data.direction,
                sender_id=data.sender_id,
                sender_name=data.sender_name,
                content=data.content,
                channel_message_id=data.channel_message_id,
                reply_to_id=data.reply_to_id,
                media_urls_json=data.media_urls,
                metadata_json=data.metadata,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return self._inbox_message_from_model(model)

    async def get_inbox_message(self, message_id: UUID) -> InboxMessage | None:
        """Get an inbox message by ID."""
        async with self._session() as session:
            result = await session.execute(
                select(InboxMessageModel).where(InboxMessageModel.id == str(message_id))
            )
            model = result.scalar_one_or_none()
            if model:
                return self._inbox_message_from_model(model)
            return None

    async def list_inbox_messages(
        self,
        session_id: UUID | None = None,
        channel: str | None = None,
        unread: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InboxMessage]:
        """List inbox messages with optional filtering."""
        async with self._session() as session:
            query = select(InboxMessageModel)
            if session_id:
                query = query.where(InboxMessageModel.session_id == str(session_id))
            if channel:
                query = query.where(InboxMessageModel.channel == channel)
            if unread is not None:
                query = query.where(InboxMessageModel.unread == unread)
            query = (
                query.order_by(InboxMessageModel.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(query)
            models = result.scalars().all()
            return [self._inbox_message_from_model(m) for m in models]

    async def mark_messages_read(
        self,
        session_id: UUID | None = None,
        message_ids: list[UUID] | None = None,
    ) -> int:
        """Mark messages as read. Returns count of messages updated."""
        async with self._session() as session:
            query = select(InboxMessageModel).where(InboxMessageModel.unread == True)

            if session_id:
                query = query.where(InboxMessageModel.session_id == str(session_id))
            if message_ids:
                query = query.where(
                    InboxMessageModel.id.in_([str(mid) for mid in message_ids])
                )

            result = await session.execute(query)
            models = result.scalars().all()

            count = 0
            for model in models:
                model.unread = False
                count += 1

            await session.commit()
            return count

    async def count_unread_messages(
        self, channel: str | None = None, session_id: UUID | None = None
    ) -> int:
        """Count unread messages."""
        from sqlalchemy import func as sql_func

        async with self._session() as session:
            query = select(sql_func.count(InboxMessageModel.id)).where(
                InboxMessageModel.unread == True
            )
            if channel:
                query = query.where(InboxMessageModel.channel == channel)
            if session_id:
                query = query.where(InboxMessageModel.session_id == str(session_id))

            result = await session.execute(query)
            return result.scalar() or 0

    def _inbox_message_from_model(self, model: InboxMessageModel) -> InboxMessage:
        """Convert SQLAlchemy model to Pydantic model."""
        return InboxMessage(
            id=UUID(model.id),
            session_id=UUID(model.session_id),
            channel=model.channel,
            direction=model.direction,
            sender_id=model.sender_id,
            sender_name=model.sender_name,
            content=model.content,
            channel_message_id=model.channel_message_id,
            reply_to_id=model.reply_to_id,
            unread=model.unread,
            media_urls=model.media_urls_json,
            created_at=model.created_at,
            metadata=model.metadata_json,
        )

    # Token Usage

    async def record_token_usage(self, data: TokenUsageCreate) -> TokenUsage:
        """Record a token usage entry."""
        async with self._session() as session:
            model = TokenUsageModel(
                conversation_id=str(data.conversation_id) if data.conversation_id else None,
                message_id=str(data.message_id) if data.message_id else None,
                user_id=str(data.user_id) if data.user_id else None,
                provider=data.provider,
                model=data.model,
                prompt_tokens=data.prompt_tokens,
                completion_tokens=data.completion_tokens,
                total_tokens=data.total_tokens,
                metadata_json=data.metadata,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return TokenUsage(
                id=UUID(model.id),
                conversation_id=UUID(model.conversation_id) if model.conversation_id else None,
                message_id=UUID(model.message_id) if model.message_id else None,
                user_id=UUID(model.user_id) if model.user_id else None,
                provider=model.provider,
                model=model.model,
                prompt_tokens=model.prompt_tokens,
                completion_tokens=model.completion_tokens,
                total_tokens=model.total_tokens,
                created_at=model.created_at,
                metadata=model.metadata_json,
            )

    async def get_token_usage_summary(
        self,
        user_id: UUID | None = None,
        conversation_id: UUID | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, Any]:
        """Get aggregated token usage summary."""
        from sqlalchemy import func as sql_func

        async with self._session() as session:
            query = select(
                TokenUsageModel.provider,
                TokenUsageModel.model,
                sql_func.sum(TokenUsageModel.prompt_tokens).label("total_prompt"),
                sql_func.sum(TokenUsageModel.completion_tokens).label("total_completion"),
                sql_func.sum(TokenUsageModel.total_tokens).label("total_tokens"),
                sql_func.count(TokenUsageModel.id).label("request_count"),
            ).group_by(TokenUsageModel.provider, TokenUsageModel.model)

            if user_id:
                query = query.where(TokenUsageModel.user_id == str(user_id))
            if conversation_id:
                query = query.where(TokenUsageModel.conversation_id == str(conversation_id))
            if start_date:
                query = query.where(TokenUsageModel.created_at >= start_date)
            if end_date:
                query = query.where(TokenUsageModel.created_at <= end_date)

            result = await session.execute(query)
            rows = result.all()

            breakdown = []
            totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "request_count": 0}
            for row in rows:
                entry = {
                    "provider": row.provider,
                    "model": row.model,
                    "prompt_tokens": row.total_prompt or 0,
                    "completion_tokens": row.total_completion or 0,
                    "total_tokens": row.total_tokens or 0,
                    "request_count": row.request_count or 0,
                }
                breakdown.append(entry)
                totals["prompt_tokens"] += entry["prompt_tokens"]
                totals["completion_tokens"] += entry["completion_tokens"]
                totals["total_tokens"] += entry["total_tokens"]
                totals["request_count"] += entry["request_count"]

            return {"totals": totals, "breakdown": breakdown}
