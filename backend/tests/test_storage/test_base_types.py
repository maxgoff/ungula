"""
Tests for Pydantic models in ungula.storage.base.

Covers all storage type definitions: User, Conversation, Message, Task,
AgentRecord, MemoryEntry, Session, and InboxMessage create/read models,
plus TaskStatus and AgentStatus constants.
"""

from datetime import datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ungula.storage.base import (
    AgentRecord,
    AgentRecordCreate,
    AgentStatus,
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
    Task,
    TaskCreate,
    TaskStatus,
    User,
    UserCreate,
    UserInDB,
)


# ---------------------------------------------------------------------------
# UserCreate
# ---------------------------------------------------------------------------


class TestUserCreate:
    """Tests for UserCreate model."""

    def test_required_fields_only(self):
        """UserCreate needs email and password; name is optional."""
        user = UserCreate(email="a@b.com", password="secret")
        assert user.email == "a@b.com"
        assert user.password == "secret"
        assert user.name is None

    def test_all_fields(self):
        """UserCreate with all fields populated."""
        user = UserCreate(email="a@b.com", password="secret", name="Alice")
        assert user.name == "Alice"

    def test_missing_email_raises(self):
        """email is required."""
        with pytest.raises(ValidationError):
            UserCreate(password="secret")

    def test_missing_password_raises(self):
        """password is required."""
        with pytest.raises(ValidationError):
            UserCreate(email="a@b.com")


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class TestUser:
    """Tests for User model."""

    def test_creation_with_all_fields(self):
        uid = uuid4()
        now = datetime.utcnow()
        user = User(
            id=uid,
            email="a@b.com",
            name="Alice",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        assert user.id == uid
        assert user.email == "a@b.com"
        assert user.name == "Alice"
        assert user.is_active is True
        assert user.created_at == now

    def test_default_values(self):
        """is_active defaults to True; name defaults to None."""
        uid = uuid4()
        now = datetime.utcnow()
        user = User(id=uid, email="a@b.com", created_at=now, updated_at=now)
        assert user.is_active is True
        assert user.name is None

    def test_id_must_be_uuid(self):
        """id field should accept UUID objects."""
        now = datetime.utcnow()
        uid = uuid4()
        user = User(id=uid, email="x@y.com", created_at=now, updated_at=now)
        assert isinstance(user.id, UUID)

    def test_id_accepts_uuid_string(self):
        """Pydantic should coerce a valid UUID string to UUID."""
        now = datetime.utcnow()
        uid = str(uuid4())
        user = User(id=uid, email="x@y.com", created_at=now, updated_at=now)
        assert isinstance(user.id, UUID)

    def test_invalid_id_raises(self):
        """A non-UUID string should raise ValidationError."""
        now = datetime.utcnow()
        with pytest.raises(ValidationError):
            User(id="not-a-uuid", email="x@y.com", created_at=now, updated_at=now)


# ---------------------------------------------------------------------------
# UserInDB
# ---------------------------------------------------------------------------


class TestUserInDB:
    """Tests for UserInDB model."""

    def test_inherits_user_fields(self):
        uid = uuid4()
        now = datetime.utcnow()
        user_db = UserInDB(
            id=uid,
            email="a@b.com",
            hashed_password="hashed123",
            created_at=now,
            updated_at=now,
        )
        assert user_db.email == "a@b.com"
        assert user_db.hashed_password == "hashed123"
        assert isinstance(user_db, User)

    def test_hashed_password_required(self):
        uid = uuid4()
        now = datetime.utcnow()
        with pytest.raises(ValidationError):
            UserInDB(id=uid, email="a@b.com", created_at=now, updated_at=now)


# ---------------------------------------------------------------------------
# ConversationCreate
# ---------------------------------------------------------------------------


class TestConversationCreate:
    """Tests for ConversationCreate model."""

    def test_no_required_fields(self):
        """All fields have defaults or are optional."""
        conv = ConversationCreate()
        assert conv.title is None
        assert conv.user_id is None
        assert conv.metadata == {}

    def test_all_fields(self):
        uid = uuid4()
        conv = ConversationCreate(
            title="Chat", user_id=uid, metadata={"topic": "AI"}
        )
        assert conv.title == "Chat"
        assert conv.user_id == uid
        assert conv.metadata == {"topic": "AI"}

    def test_metadata_default_factory(self):
        """Each instance gets its own metadata dict."""
        a = ConversationCreate()
        b = ConversationCreate()
        a.metadata["key"] = "value"
        assert "key" not in b.metadata


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------


class TestConversation:
    """Tests for Conversation read model."""

    def test_creation(self):
        cid = uuid4()
        now = datetime.utcnow()
        conv = Conversation(id=cid, created_at=now, updated_at=now)
        assert conv.id == cid
        assert conv.user_id is None
        assert conv.title is None
        assert conv.metadata == {}

    def test_all_fields(self):
        cid = uuid4()
        uid = uuid4()
        now = datetime.utcnow()
        conv = Conversation(
            id=cid,
            user_id=uid,
            title="Test",
            created_at=now,
            updated_at=now,
            metadata={"k": "v"},
        )
        assert conv.user_id == uid
        assert conv.title == "Test"
        assert conv.metadata == {"k": "v"}


# ---------------------------------------------------------------------------
# MessageCreate
# ---------------------------------------------------------------------------


class TestMessageCreate:
    """Tests for MessageCreate model."""

    def test_required_fields(self):
        cid = uuid4()
        msg = MessageCreate(conversation_id=cid, role="user", content="Hi")
        assert msg.conversation_id == cid
        assert msg.role == "user"
        assert msg.content == "Hi"

    def test_optional_fields_default(self):
        cid = uuid4()
        msg = MessageCreate(conversation_id=cid, role="user", content="Hi")
        assert msg.agent_id is None
        assert msg.model is None
        assert msg.stage1 is None
        assert msg.stage2 is None
        assert msg.stage3 is None
        assert msg.metadata == {}

    def test_all_fields(self):
        cid = uuid4()
        msg = MessageCreate(
            conversation_id=cid,
            role="assistant",
            content="Hello",
            agent_id="agent-1",
            model="gpt-4",
            stage1=[{"model": "a", "response": "x"}],
            stage2=[{"rank": 1}],
            stage3={"synthesis": "final"},
            metadata={"tool": "search"},
        )
        assert msg.agent_id == "agent-1"
        assert msg.model == "gpt-4"
        assert len(msg.stage1) == 1
        assert len(msg.stage2) == 1
        assert msg.stage3["synthesis"] == "final"

    def test_missing_role_raises(self):
        with pytest.raises(ValidationError):
            MessageCreate(conversation_id=uuid4(), content="Hi")

    def test_missing_content_raises(self):
        with pytest.raises(ValidationError):
            MessageCreate(conversation_id=uuid4(), role="user")


# ---------------------------------------------------------------------------
# Message (read model)
# ---------------------------------------------------------------------------


class TestMessage:
    """Tests for Message read model."""

    def test_creation(self):
        mid = uuid4()
        cid = uuid4()
        now = datetime.utcnow()
        msg = Message(
            id=mid,
            conversation_id=cid,
            role="user",
            content="Hello",
            created_at=now,
        )
        assert msg.id == mid
        assert msg.conversation_id == cid
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_optional_fields(self):
        mid = uuid4()
        cid = uuid4()
        now = datetime.utcnow()
        msg = Message(
            id=mid, conversation_id=cid, role="user", content="Hi", created_at=now
        )
        assert msg.agent_id is None
        assert msg.model is None
        assert msg.stage1 is None
        assert msg.stage2 is None
        assert msg.stage3 is None
        assert msg.metadata == {}


# ---------------------------------------------------------------------------
# TaskCreate / TaskStatus / Task
# ---------------------------------------------------------------------------


class TestTaskStatus:
    """Tests for TaskStatus constants."""

    def test_all_statuses(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.BLOCKED == "blocked"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.CANCELLED == "cancelled"

    def test_status_values_are_strings(self):
        for attr in ("PENDING", "RUNNING", "BLOCKED", "COMPLETED", "FAILED", "CANCELLED"):
            assert isinstance(getattr(TaskStatus, attr), str)


class TestTaskCreate:
    """Tests for TaskCreate model."""

    def test_required_field_only(self):
        task = TaskCreate(title="Deploy")
        assert task.title == "Deploy"
        assert task.description is None
        assert task.agent_id is None
        assert task.parent_task_id is None
        assert task.priority == 0
        assert task.metadata == {}

    def test_all_fields(self):
        parent_id = uuid4()
        task = TaskCreate(
            title="Deploy",
            description="Deploy v2",
            agent_id="agent-1",
            parent_task_id=parent_id,
            priority=5,
            metadata={"env": "prod"},
        )
        assert task.description == "Deploy v2"
        assert task.agent_id == "agent-1"
        assert task.parent_task_id == parent_id
        assert task.priority == 5


class TestTask:
    """Tests for Task read model."""

    def test_creation_with_defaults(self):
        tid = uuid4()
        now = datetime.utcnow()
        task = Task(id=tid, title="Build", created_at=now)
        assert task.id == tid
        assert task.status == TaskStatus.PENDING
        assert task.priority == 0
        assert task.result is None
        assert task.error is None
        assert task.blocked_reason is None
        assert task.started_at is None
        assert task.completed_at is None
        assert task.metadata == {}

    def test_full_task(self):
        tid = uuid4()
        parent = uuid4()
        now = datetime.utcnow()
        task = Task(
            id=tid,
            title="Build",
            description="Build project",
            status=TaskStatus.COMPLETED,
            agent_id="agent-1",
            parent_task_id=parent,
            priority=10,
            result="Success",
            error=None,
            blocked_reason=None,
            created_at=now,
            started_at=now,
            completed_at=now,
            metadata={"version": "2.0"},
        )
        assert task.status == "completed"
        assert task.result == "Success"
        assert task.parent_task_id == parent


# ---------------------------------------------------------------------------
# AgentRecordCreate / AgentStatus / AgentRecord
# ---------------------------------------------------------------------------


class TestAgentStatus:
    """Tests for AgentStatus constants."""

    def test_all_statuses(self):
        assert AgentStatus.STOPPED == "stopped"
        assert AgentStatus.STARTING == "starting"
        assert AgentStatus.RUNNING == "running"
        assert AgentStatus.STOPPING == "stopping"
        assert AgentStatus.ERROR == "error"

    def test_status_values_are_strings(self):
        for attr in ("STOPPED", "STARTING", "RUNNING", "STOPPING", "ERROR"):
            assert isinstance(getattr(AgentStatus, attr), str)


class TestAgentRecordCreate:
    """Tests for AgentRecordCreate model."""

    def test_required_fields(self):
        agent = AgentRecordCreate(id="agent-1", name="Alpha", type="chat")
        assert agent.id == "agent-1"
        assert agent.name == "Alpha"
        assert agent.type == "chat"
        assert agent.config == {}

    def test_with_config(self):
        agent = AgentRecordCreate(
            id="agent-2",
            name="Beta",
            type="tool",
            config={"model": "gpt-4", "temperature": 0.5},
        )
        assert agent.config["model"] == "gpt-4"


class TestAgentRecord:
    """Tests for AgentRecord read model."""

    def test_defaults(self):
        now = datetime.utcnow()
        agent = AgentRecord(
            id="agent-1", name="Alpha", type="chat", created_at=now, updated_at=now
        )
        assert agent.status == AgentStatus.STOPPED
        assert agent.config == {}
        assert agent.last_heartbeat is None

    def test_all_fields(self):
        now = datetime.utcnow()
        agent = AgentRecord(
            id="agent-1",
            name="Alpha",
            type="chat",
            status=AgentStatus.RUNNING,
            config={"k": "v"},
            last_heartbeat=now,
            created_at=now,
            updated_at=now,
        )
        assert agent.status == "running"
        assert agent.last_heartbeat == now


# ---------------------------------------------------------------------------
# MemoryEntryCreate / MemoryEntry
# ---------------------------------------------------------------------------


class TestMemoryEntryCreate:
    """Tests for MemoryEntryCreate model."""

    def test_required_fields(self):
        mem = MemoryEntryCreate(content="The user likes Python", memory_type="preference")
        assert mem.content == "The user likes Python"
        assert mem.memory_type == "preference"

    def test_defaults(self):
        mem = MemoryEntryCreate(content="fact", memory_type="fact")
        assert mem.level == "global"
        assert mem.project_id is None
        assert mem.agent_id is None
        assert mem.source is None
        assert mem.embedding is None
        assert mem.metadata == {}

    def test_all_fields(self):
        mem = MemoryEntryCreate(
            content="Use async",
            memory_type="decision",
            level="project",
            project_id="proj-1",
            agent_id="agent-1",
            source="conversation",
            embedding=[0.1, 0.2, 0.3],
            metadata={"importance": "high"},
        )
        assert mem.level == "project"
        assert mem.embedding == [0.1, 0.2, 0.3]
        assert mem.source == "conversation"


class TestMemoryEntry:
    """Tests for MemoryEntry read model."""

    def test_creation(self):
        mid = uuid4()
        now = datetime.utcnow()
        entry = MemoryEntry(
            id=mid,
            content="fact",
            memory_type="fact",
            level="global",
            created_at=now,
            accessed_at=now,
        )
        assert entry.id == mid
        assert entry.access_count == 0
        assert entry.metadata == {}

    def test_all_fields(self):
        mid = uuid4()
        now = datetime.utcnow()
        entry = MemoryEntry(
            id=mid,
            content="Remember this",
            memory_type="pattern",
            level="agent",
            project_id="proj-1",
            agent_id="agent-1",
            source="chat",
            embedding=[1.0, 2.0],
            created_at=now,
            accessed_at=now,
            access_count=5,
            metadata={"tag": "important"},
        )
        assert entry.access_count == 5
        assert entry.embedding == [1.0, 2.0]


# ---------------------------------------------------------------------------
# SessionCreate / Session
# ---------------------------------------------------------------------------


class TestSessionCreate:
    """Tests for SessionCreate model."""

    def test_required_fields(self):
        sess = SessionCreate(channel="discord", contact_id="user-123")
        assert sess.channel == "discord"
        assert sess.contact_id == "user-123"

    def test_defaults(self):
        sess = SessionCreate(channel="discord", contact_id="user-123")
        assert sess.contact_name is None
        assert sess.conversation_id is None
        assert sess.chat_type == "direct"
        assert sess.metadata == {}

    def test_all_fields(self):
        cid = uuid4()
        sess = SessionCreate(
            channel="telegram",
            contact_id="user-456",
            contact_name="Bob",
            conversation_id=cid,
            chat_type="group",
            metadata={"server": "main"},
        )
        assert sess.contact_name == "Bob"
        assert sess.conversation_id == cid
        assert sess.chat_type == "group"


class TestSession:
    """Tests for Session read model."""

    def test_creation(self):
        sid = uuid4()
        now = datetime.utcnow()
        sess = Session(
            id=sid,
            channel="discord",
            contact_id="user-123",
            last_activity=now,
            created_at=now,
        )
        assert sess.id == sid
        assert sess.active is True
        assert sess.message_count == 0
        assert sess.chat_type == "direct"

    def test_all_fields(self):
        sid = uuid4()
        cid = uuid4()
        now = datetime.utcnow()
        sess = Session(
            id=sid,
            channel="telegram",
            contact_id="user-456",
            contact_name="Alice",
            conversation_id=cid,
            chat_type="group",
            active=False,
            last_activity=now,
            message_count=42,
            created_at=now,
            metadata={"server": "main"},
        )
        assert sess.active is False
        assert sess.message_count == 42
        assert sess.conversation_id == cid


# ---------------------------------------------------------------------------
# InboxMessageCreate / InboxMessage
# ---------------------------------------------------------------------------


class TestInboxMessageCreate:
    """Tests for InboxMessageCreate model."""

    def test_required_fields(self):
        sid = uuid4()
        msg = InboxMessageCreate(
            session_id=sid,
            channel="discord",
            direction="inbound",
            sender_id="user-1",
            content="Hello!",
        )
        assert msg.session_id == sid
        assert msg.channel == "discord"
        assert msg.direction == "inbound"
        assert msg.sender_id == "user-1"
        assert msg.content == "Hello!"

    def test_defaults(self):
        sid = uuid4()
        msg = InboxMessageCreate(
            session_id=sid,
            channel="discord",
            direction="inbound",
            sender_id="user-1",
            content="Hi",
        )
        assert msg.sender_name is None
        assert msg.channel_message_id is None
        assert msg.reply_to_id is None
        assert msg.metadata == {}

    def test_all_fields(self):
        sid = uuid4()
        msg = InboxMessageCreate(
            session_id=sid,
            channel="telegram",
            direction="outbound",
            sender_id="bot-1",
            sender_name="MyBot",
            content="Reply",
            channel_message_id="msg-789",
            reply_to_id="msg-456",
            metadata={"attachments": 1},
        )
        assert msg.sender_name == "MyBot"
        assert msg.channel_message_id == "msg-789"
        assert msg.reply_to_id == "msg-456"


class TestInboxMessage:
    """Tests for InboxMessage read model."""

    def test_creation(self):
        mid = uuid4()
        sid = uuid4()
        now = datetime.utcnow()
        msg = InboxMessage(
            id=mid,
            session_id=sid,
            channel="discord",
            direction="inbound",
            sender_id="user-1",
            content="Hello",
            created_at=now,
        )
        assert msg.id == mid
        assert msg.unread is True
        assert msg.metadata == {}

    def test_all_fields(self):
        mid = uuid4()
        sid = uuid4()
        now = datetime.utcnow()
        msg = InboxMessage(
            id=mid,
            session_id=sid,
            channel="telegram",
            direction="outbound",
            sender_id="bot-1",
            sender_name="MyBot",
            content="Goodbye",
            channel_message_id="msg-100",
            reply_to_id="msg-99",
            unread=False,
            created_at=now,
            metadata={"priority": "high"},
        )
        assert msg.unread is False
        assert msg.sender_name == "MyBot"
        assert msg.channel_message_id == "msg-100"

    def test_session_id_is_uuid(self):
        mid = uuid4()
        sid = uuid4()
        now = datetime.utcnow()
        msg = InboxMessage(
            id=mid,
            session_id=sid,
            channel="discord",
            direction="inbound",
            sender_id="user-1",
            content="Hi",
            created_at=now,
        )
        assert isinstance(msg.session_id, UUID)
