"""
Tests for SQLAlchemy models in ungula.storage.models.

Covers table names, generate_uuid(), model instantiation, async
in-memory SQLite database round-trips, relationships, and cascade deletes.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ungula.storage.models import (
    AgentModel,
    Base,
    ConversationModel,
    InboxMessageModel,
    MemoryModel,
    MessageModel,
    SessionModel,
    TaskModel,
    UserModel,
    generate_uuid,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def async_engine():
    """Create an in-memory async SQLite engine and tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session(async_engine):
    """Provide an async session scoped to a single test."""
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# generate_uuid()
# ---------------------------------------------------------------------------


class TestGenerateUuid:
    """Tests for generate_uuid helper."""

    def test_returns_string(self):
        result = generate_uuid()
        assert isinstance(result, str)

    def test_is_valid_uuid(self):
        result = generate_uuid()
        parsed = uuid.UUID(result)
        assert str(parsed) == result

    def test_uniqueness(self):
        ids = {generate_uuid() for _ in range(100)}
        assert len(ids) == 100


# ---------------------------------------------------------------------------
# Table names
# ---------------------------------------------------------------------------


class TestTableNames:
    """Verify __tablename__ for every model."""

    def test_user_model(self):
        assert UserModel.__tablename__ == "users"

    def test_conversation_model(self):
        assert ConversationModel.__tablename__ == "conversations"

    def test_message_model(self):
        assert MessageModel.__tablename__ == "messages"

    def test_task_model(self):
        assert TaskModel.__tablename__ == "tasks"

    def test_agent_model(self):
        assert AgentModel.__tablename__ == "agents"

    def test_memory_model(self):
        assert MemoryModel.__tablename__ == "memories"

    def test_session_model(self):
        assert SessionModel.__tablename__ == "sessions"

    def test_inbox_message_model(self):
        assert InboxMessageModel.__tablename__ == "inbox_messages"


# ---------------------------------------------------------------------------
# Basic instantiation (no DB)
# ---------------------------------------------------------------------------


class TestModelInstantiation:
    """Test that models can be instantiated with required fields."""

    def test_user_model(self):
        user = UserModel(email="a@b.com", hashed_password="hash")
        assert user.email == "a@b.com"
        assert user.hashed_password == "hash"

    def test_conversation_model(self):
        conv = ConversationModel(title="Chat")
        assert conv.title == "Chat"

    def test_message_model(self):
        msg = MessageModel(
            conversation_id="fake-id", role="user", content="Hello"
        )
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_task_model(self):
        task = TaskModel(title="Build")
        assert task.title == "Build"

    def test_agent_model(self):
        agent = AgentModel(id="agent-1", name="Alpha", type="chat")
        assert agent.id == "agent-1"

    def test_memory_model(self):
        mem = MemoryModel(content="fact", memory_type="fact")
        assert mem.content == "fact"

    def test_session_model(self):
        sess = SessionModel(channel="discord", contact_id="user-1")
        assert sess.channel == "discord"

    def test_inbox_message_model(self):
        msg = InboxMessageModel(
            session_id="fake-id",
            channel="discord",
            direction="inbound",
            sender_id="user-1",
            content="Hi",
        )
        assert msg.direction == "inbound"


# ---------------------------------------------------------------------------
# Database round-trip tests
# ---------------------------------------------------------------------------


class TestUserModelDB:
    """Test UserModel persistence."""

    @pytest.mark.asyncio
    async def test_insert_and_query(self, async_session: AsyncSession):
        user = UserModel(email="test@example.com", hashed_password="hash123", name="Test")
        async_session.add(user)
        await async_session.commit()

        result = await async_session.execute(
            select(UserModel).where(UserModel.email == "test@example.com")
        )
        fetched = result.scalar_one()
        assert fetched.email == "test@example.com"
        assert fetched.name == "Test"
        assert fetched.is_active is True
        # id should have been auto-generated
        assert fetched.id is not None
        uuid.UUID(fetched.id)  # validates it is a UUID

    @pytest.mark.asyncio
    async def test_unique_email_constraint(self, async_session: AsyncSession):
        """Inserting two users with same email should fail."""
        from sqlalchemy.exc import IntegrityError

        user1 = UserModel(email="dup@test.com", hashed_password="h1")
        user2 = UserModel(email="dup@test.com", hashed_password="h2")
        async_session.add(user1)
        await async_session.commit()
        async_session.add(user2)
        with pytest.raises(IntegrityError):
            await async_session.commit()


class TestConversationModelDB:
    """Test ConversationModel persistence."""

    @pytest.mark.asyncio
    async def test_insert_and_query(self, async_session: AsyncSession):
        conv = ConversationModel(title="Test Chat")
        async_session.add(conv)
        await async_session.commit()

        result = await async_session.execute(
            select(ConversationModel).where(ConversationModel.title == "Test Chat")
        )
        fetched = result.scalar_one()
        assert fetched.title == "Test Chat"
        assert fetched.id is not None

    @pytest.mark.asyncio
    async def test_metadata_json(self, async_session: AsyncSession):
        conv = ConversationModel(title="Meta", metadata_json={"topic": "AI"})
        async_session.add(conv)
        await async_session.commit()

        result = await async_session.execute(
            select(ConversationModel).where(ConversationModel.title == "Meta")
        )
        fetched = result.scalar_one()
        assert fetched.metadata_json == {"topic": "AI"}


class TestMessageModelDB:
    """Test MessageModel persistence."""

    @pytest.mark.asyncio
    async def test_insert_and_query(self, async_session: AsyncSession):
        conv = ConversationModel(title="Chat")
        async_session.add(conv)
        await async_session.commit()

        msg = MessageModel(
            conversation_id=conv.id, role="user", content="Hello world"
        )
        async_session.add(msg)
        await async_session.commit()

        result = await async_session.execute(
            select(MessageModel).where(MessageModel.conversation_id == conv.id)
        )
        fetched = result.scalar_one()
        assert fetched.role == "user"
        assert fetched.content == "Hello world"

    @pytest.mark.asyncio
    async def test_stage_json_fields(self, async_session: AsyncSession):
        conv = ConversationModel(title="Stages")
        async_session.add(conv)
        await async_session.commit()

        msg = MessageModel(
            conversation_id=conv.id,
            role="assistant",
            content="Response",
            stage1_json=[{"model": "gpt-4", "text": "a"}],
            stage2_json=[{"rank": 1}],
            stage3_json={"synthesis": "final"},
        )
        async_session.add(msg)
        await async_session.commit()

        result = await async_session.execute(
            select(MessageModel).where(MessageModel.id == msg.id)
        )
        fetched = result.scalar_one()
        assert fetched.stage1_json == [{"model": "gpt-4", "text": "a"}]
        assert fetched.stage2_json == [{"rank": 1}]
        assert fetched.stage3_json == {"synthesis": "final"}


class TestTaskModelDB:
    """Test TaskModel persistence."""

    @pytest.mark.asyncio
    async def test_insert_and_query(self, async_session: AsyncSession):
        task = TaskModel(title="Deploy", description="Deploy v2", priority=5)
        async_session.add(task)
        await async_session.commit()

        result = await async_session.execute(
            select(TaskModel).where(TaskModel.title == "Deploy")
        )
        fetched = result.scalar_one()
        assert fetched.status == "pending"
        assert fetched.priority == 5
        assert fetched.description == "Deploy v2"

    @pytest.mark.asyncio
    async def test_parent_child_relationship(self, async_session: AsyncSession):
        parent = TaskModel(title="Parent")
        async_session.add(parent)
        await async_session.commit()

        child = TaskModel(title="Child", parent_task_id=parent.id)
        async_session.add(child)
        await async_session.commit()

        result = await async_session.execute(
            select(TaskModel).where(TaskModel.id == child.id)
        )
        fetched_child = result.scalar_one()
        assert fetched_child.parent_task_id == parent.id


class TestAgentModelDB:
    """Test AgentModel persistence."""

    @pytest.mark.asyncio
    async def test_insert_and_query(self, async_session: AsyncSession):
        agent = AgentModel(id="agent-1", name="Alpha", type="chat")
        async_session.add(agent)
        await async_session.commit()

        result = await async_session.execute(
            select(AgentModel).where(AgentModel.id == "agent-1")
        )
        fetched = result.scalar_one()
        assert fetched.name == "Alpha"
        assert fetched.type == "chat"
        assert fetched.status == "stopped"


class TestMemoryModelDB:
    """Test MemoryModel persistence."""

    @pytest.mark.asyncio
    async def test_insert_and_query(self, async_session: AsyncSession):
        mem = MemoryModel(
            content="The user prefers Python",
            memory_type="preference",
            level="global",
        )
        async_session.add(mem)
        await async_session.commit()

        result = await async_session.execute(
            select(MemoryModel).where(MemoryModel.memory_type == "preference")
        )
        fetched = result.scalar_one()
        assert fetched.content == "The user prefers Python"
        assert fetched.level == "global"

    @pytest.mark.asyncio
    async def test_embedding_json(self, async_session: AsyncSession):
        mem = MemoryModel(
            content="vector",
            memory_type="fact",
            embedding_json=[0.1, 0.2, 0.3],
        )
        async_session.add(mem)
        await async_session.commit()

        result = await async_session.execute(
            select(MemoryModel).where(MemoryModel.id == mem.id)
        )
        fetched = result.scalar_one()
        assert fetched.embedding_json == [0.1, 0.2, 0.3]


class TestSessionModelDB:
    """Test SessionModel persistence."""

    @pytest.mark.asyncio
    async def test_insert_and_query(self, async_session: AsyncSession):
        sess = SessionModel(channel="discord", contact_id="user-123")
        async_session.add(sess)
        await async_session.commit()

        result = await async_session.execute(
            select(SessionModel).where(SessionModel.contact_id == "user-123")
        )
        fetched = result.scalar_one()
        assert fetched.channel == "discord"
        assert fetched.chat_type == "direct"
        assert fetched.active is True


class TestInboxMessageModelDB:
    """Test InboxMessageModel persistence."""

    @pytest.mark.asyncio
    async def test_insert_and_query(self, async_session: AsyncSession):
        sess = SessionModel(channel="discord", contact_id="user-1")
        async_session.add(sess)
        await async_session.commit()

        msg = InboxMessageModel(
            session_id=sess.id,
            channel="discord",
            direction="inbound",
            sender_id="user-1",
            content="Hey!",
        )
        async_session.add(msg)
        await async_session.commit()

        result = await async_session.execute(
            select(InboxMessageModel).where(InboxMessageModel.session_id == sess.id)
        )
        fetched = result.scalar_one()
        assert fetched.content == "Hey!"
        assert fetched.unread is True


# ---------------------------------------------------------------------------
# Relationship tests
# ---------------------------------------------------------------------------


class TestRelationships:
    """Test SQLAlchemy relationship navigation."""

    @pytest.mark.asyncio
    async def test_user_to_conversations(self, async_session: AsyncSession):
        user = UserModel(email="rel@test.com", hashed_password="hash")
        async_session.add(user)
        await async_session.commit()

        conv1 = ConversationModel(title="Chat 1", user_id=user.id)
        conv2 = ConversationModel(title="Chat 2", user_id=user.id)
        async_session.add_all([conv1, conv2])
        await async_session.commit()

        result = await async_session.execute(
            select(UserModel).where(UserModel.id == user.id)
        )
        fetched_user = result.scalar_one()
        # Eagerly load relationship
        await async_session.refresh(fetched_user, ["conversations"])
        assert len(fetched_user.conversations) == 2

    @pytest.mark.asyncio
    async def test_conversation_to_messages(self, async_session: AsyncSession):
        conv = ConversationModel(title="Chat")
        async_session.add(conv)
        await async_session.commit()

        msg1 = MessageModel(conversation_id=conv.id, role="user", content="Hi")
        msg2 = MessageModel(conversation_id=conv.id, role="assistant", content="Hello")
        async_session.add_all([msg1, msg2])
        await async_session.commit()

        result = await async_session.execute(
            select(ConversationModel).where(ConversationModel.id == conv.id)
        )
        fetched_conv = result.scalar_one()
        await async_session.refresh(fetched_conv, ["messages"])
        assert len(fetched_conv.messages) == 2

    @pytest.mark.asyncio
    async def test_session_to_inbox_messages(self, async_session: AsyncSession):
        sess = SessionModel(channel="discord", contact_id="user-1")
        async_session.add(sess)
        await async_session.commit()

        msg1 = InboxMessageModel(
            session_id=sess.id,
            channel="discord",
            direction="inbound",
            sender_id="user-1",
            content="Msg 1",
        )
        msg2 = InboxMessageModel(
            session_id=sess.id,
            channel="discord",
            direction="outbound",
            sender_id="bot-1",
            content="Msg 2",
        )
        async_session.add_all([msg1, msg2])
        await async_session.commit()

        result = await async_session.execute(
            select(SessionModel).where(SessionModel.id == sess.id)
        )
        fetched_sess = result.scalar_one()
        await async_session.refresh(fetched_sess, ["inbox_messages"])
        assert len(fetched_sess.inbox_messages) == 2


# ---------------------------------------------------------------------------
# Cascade delete tests
# ---------------------------------------------------------------------------


class TestCascadeDeletes:
    """Test that cascade deletes propagate correctly."""

    @pytest.mark.asyncio
    async def test_delete_user_cascades_conversations(self, async_session: AsyncSession):
        user = UserModel(email="cascade@test.com", hashed_password="hash")
        async_session.add(user)
        await async_session.commit()

        conv = ConversationModel(title="Will be deleted", user_id=user.id)
        async_session.add(conv)
        await async_session.commit()
        conv_id = conv.id

        await async_session.delete(user)
        await async_session.commit()

        result = await async_session.execute(
            select(ConversationModel).where(ConversationModel.id == conv_id)
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_delete_conversation_cascades_messages(self, async_session: AsyncSession):
        conv = ConversationModel(title="Cascade test")
        async_session.add(conv)
        await async_session.commit()

        msg = MessageModel(conversation_id=conv.id, role="user", content="Bye")
        async_session.add(msg)
        await async_session.commit()
        msg_id = msg.id

        await async_session.delete(conv)
        await async_session.commit()

        result = await async_session.execute(
            select(MessageModel).where(MessageModel.id == msg_id)
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_delete_session_cascades_inbox_messages(self, async_session: AsyncSession):
        sess = SessionModel(channel="discord", contact_id="user-x")
        async_session.add(sess)
        await async_session.commit()

        msg = InboxMessageModel(
            session_id=sess.id,
            channel="discord",
            direction="inbound",
            sender_id="user-x",
            content="Cascade me",
        )
        async_session.add(msg)
        await async_session.commit()
        msg_id = msg.id

        await async_session.delete(sess)
        await async_session.commit()

        result = await async_session.execute(
            select(InboxMessageModel).where(InboxMessageModel.id == msg_id)
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_delete_user_cascades_through_conversations_to_messages(
        self, async_session: AsyncSession
    ):
        """Deleting a user should cascade through conversations to messages."""
        user = UserModel(email="deep@cascade.com", hashed_password="hash")
        async_session.add(user)
        await async_session.commit()

        conv = ConversationModel(title="Deep cascade", user_id=user.id)
        async_session.add(conv)
        await async_session.commit()

        msg = MessageModel(conversation_id=conv.id, role="user", content="Deep")
        async_session.add(msg)
        await async_session.commit()
        msg_id = msg.id

        await async_session.delete(user)
        await async_session.commit()

        result = await async_session.execute(
            select(MessageModel).where(MessageModel.id == msg_id)
        )
        assert result.scalar_one_or_none() is None
