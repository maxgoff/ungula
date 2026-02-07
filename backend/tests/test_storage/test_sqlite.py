"""
Tests for SQLite storage backend.
"""

from uuid import uuid4

import pytest

from ungula.storage import (
    AgentRecordCreate,
    AgentStatus,
    ConversationCreate,
    MemoryEntryCreate,
    MessageCreate,
    SQLiteStorage,
    TaskCreate,
    TaskStatus,
)


class TestConversations:
    """Tests for conversation operations."""

    @pytest.mark.asyncio
    async def test_create_conversation(self, storage: SQLiteStorage):
        """Test creating a conversation."""
        data = ConversationCreate(title="Test Conversation")
        conversation = await storage.create_conversation(data)

        assert conversation.id is not None
        assert conversation.title == "Test Conversation"
        assert conversation.created_at is not None
        assert conversation.updated_at is not None

    @pytest.mark.asyncio
    async def test_create_conversation_with_metadata(self, storage: SQLiteStorage):
        """Test creating a conversation with metadata."""
        data = ConversationCreate(
            title="Test", metadata={"key": "value", "number": 42}
        )
        conversation = await storage.create_conversation(data)

        assert conversation.metadata == {"key": "value", "number": 42}

    @pytest.mark.asyncio
    async def test_get_conversation(self, storage: SQLiteStorage):
        """Test getting a conversation by ID."""
        data = ConversationCreate(title="Test")
        created = await storage.create_conversation(data)

        retrieved = await storage.get_conversation(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.title == created.title

    @pytest.mark.asyncio
    async def test_get_conversation_not_found(self, storage: SQLiteStorage):
        """Test getting a nonexistent conversation returns None."""
        result = await storage.get_conversation(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_list_conversations(self, storage: SQLiteStorage):
        """Test listing conversations."""
        # Create multiple conversations
        for i in range(5):
            await storage.create_conversation(ConversationCreate(title=f"Conv {i}"))

        conversations = await storage.list_conversations()
        assert len(conversations) == 5

    @pytest.mark.asyncio
    async def test_list_conversations_pagination(self, storage: SQLiteStorage):
        """Test listing conversations with pagination."""
        for i in range(10):
            await storage.create_conversation(ConversationCreate(title=f"Conv {i}"))

        page1 = await storage.list_conversations(limit=5, offset=0)
        page2 = await storage.list_conversations(limit=5, offset=5)

        assert len(page1) == 5
        assert len(page2) == 5

        # Verify no overlap
        page1_ids = {c.id for c in page1}
        page2_ids = {c.id for c in page2}
        assert page1_ids.isdisjoint(page2_ids)

    @pytest.mark.asyncio
    async def test_delete_conversation(self, storage: SQLiteStorage):
        """Test deleting a conversation."""
        data = ConversationCreate(title="To Delete")
        created = await storage.create_conversation(data)

        result = await storage.delete_conversation(created.id)
        assert result is True

        retrieved = await storage.get_conversation(created.id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_conversation_not_found(self, storage: SQLiteStorage):
        """Test deleting a nonexistent conversation returns False."""
        result = await storage.delete_conversation(uuid4())
        assert result is False


class TestMessages:
    """Tests for message operations."""

    @pytest.mark.asyncio
    async def test_create_message(self, storage: SQLiteStorage):
        """Test creating a message."""
        conv = await storage.create_conversation(ConversationCreate(title="Test"))

        data = MessageCreate(
            conversation_id=conv.id,
            role="user",
            content="Hello, world!",
        )
        message = await storage.create_message(data)

        assert message.id is not None
        assert message.conversation_id == conv.id
        assert message.role == "user"
        assert message.content == "Hello, world!"

    @pytest.mark.asyncio
    async def test_create_message_with_agent(self, storage: SQLiteStorage):
        """Test creating a message with agent metadata."""
        conv = await storage.create_conversation(ConversationCreate(title="Test"))

        data = MessageCreate(
            conversation_id=conv.id,
            role="assistant",
            content="Response",
            agent_id="coder",
            model="claude-3-opus",
        )
        message = await storage.create_message(data)

        assert message.agent_id == "coder"
        assert message.model == "claude-3-opus"

    @pytest.mark.asyncio
    async def test_create_message_with_stages(self, storage: SQLiteStorage):
        """Test creating a message with multi-model stages."""
        conv = await storage.create_conversation(ConversationCreate(title="Test"))

        stage1 = [
            {"model": "gpt-4", "response": "Response 1"},
            {"model": "claude-3", "response": "Response 2"},
        ]
        stage2 = [
            {"model": "gpt-4", "ranking": "1,2"},
        ]
        stage3 = {"model": "claude-3", "response": "Final synthesis"}

        data = MessageCreate(
            conversation_id=conv.id,
            role="assistant",
            content="Final response",
            stage1=stage1,
            stage2=stage2,
            stage3=stage3,
        )
        message = await storage.create_message(data)

        assert message.stage1 == stage1
        assert message.stage2 == stage2
        assert message.stage3 == stage3

    @pytest.mark.asyncio
    async def test_get_message(self, storage: SQLiteStorage):
        """Test getting a message by ID."""
        conv = await storage.create_conversation(ConversationCreate(title="Test"))
        data = MessageCreate(
            conversation_id=conv.id, role="user", content="Test message"
        )
        created = await storage.create_message(data)

        retrieved = await storage.get_message(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.content == created.content

    @pytest.mark.asyncio
    async def test_list_messages(self, storage: SQLiteStorage):
        """Test listing messages in a conversation."""
        conv = await storage.create_conversation(ConversationCreate(title="Test"))

        for i in range(5):
            await storage.create_message(
                MessageCreate(
                    conversation_id=conv.id,
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"Message {i}",
                )
            )

        messages = await storage.list_messages(conv.id)
        assert len(messages) == 5

        # Verify order (oldest first)
        for i, msg in enumerate(messages):
            assert msg.content == f"Message {i}"


class TestTasks:
    """Tests for task operations."""

    @pytest.mark.asyncio
    async def test_create_task(self, storage: SQLiteStorage):
        """Test creating a task."""
        data = TaskCreate(title="Test Task", description="A test task")
        task = await storage.create_task(data)

        assert task.id is not None
        assert task.title == "Test Task"
        assert task.description == "A test task"
        assert task.status == TaskStatus.PENDING

    @pytest.mark.asyncio
    async def test_create_task_with_agent(self, storage: SQLiteStorage):
        """Test creating a task assigned to an agent."""
        data = TaskCreate(title="Coding Task", agent_id="coder", priority=10)
        task = await storage.create_task(data)

        assert task.agent_id == "coder"
        assert task.priority == 10

    @pytest.mark.asyncio
    async def test_get_task(self, storage: SQLiteStorage):
        """Test getting a task by ID."""
        data = TaskCreate(title="Test")
        created = await storage.create_task(data)

        retrieved = await storage.get_task(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id

    @pytest.mark.asyncio
    async def test_list_tasks_by_status(self, storage: SQLiteStorage):
        """Test listing tasks filtered by status."""
        await storage.create_task(TaskCreate(title="Pending 1"))
        await storage.create_task(TaskCreate(title="Pending 2"))

        task3 = await storage.create_task(TaskCreate(title="Running"))
        await storage.update_task_status(task3.id, TaskStatus.RUNNING)

        pending = await storage.list_tasks(status=TaskStatus.PENDING)
        running = await storage.list_tasks(status=TaskStatus.RUNNING)

        assert len(pending) == 2
        assert len(running) == 1

    @pytest.mark.asyncio
    async def test_list_tasks_by_agent(self, storage: SQLiteStorage):
        """Test listing tasks filtered by agent."""
        await storage.create_task(TaskCreate(title="Task 1", agent_id="coder"))
        await storage.create_task(TaskCreate(title="Task 2", agent_id="coder"))
        await storage.create_task(TaskCreate(title="Task 3", agent_id="researcher"))

        coder_tasks = await storage.list_tasks(agent_id="coder")
        researcher_tasks = await storage.list_tasks(agent_id="researcher")

        assert len(coder_tasks) == 2
        assert len(researcher_tasks) == 1

    @pytest.mark.asyncio
    async def test_update_task_status_running(self, storage: SQLiteStorage):
        """Test updating task status to running."""
        task = await storage.create_task(TaskCreate(title="Test"))

        updated = await storage.update_task_status(task.id, TaskStatus.RUNNING)

        assert updated is not None
        assert updated.status == TaskStatus.RUNNING
        assert updated.started_at is not None

    @pytest.mark.asyncio
    async def test_update_task_status_completed(self, storage: SQLiteStorage):
        """Test updating task status to completed."""
        task = await storage.create_task(TaskCreate(title="Test"))
        await storage.update_task_status(task.id, TaskStatus.RUNNING)

        updated = await storage.update_task_status(
            task.id, TaskStatus.COMPLETED, result="Task completed successfully"
        )

        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED
        assert updated.result == "Task completed successfully"
        assert updated.completed_at is not None

    @pytest.mark.asyncio
    async def test_update_task_status_blocked(self, storage: SQLiteStorage):
        """Test updating task status to blocked."""
        task = await storage.create_task(TaskCreate(title="Test"))
        await storage.update_task_status(task.id, TaskStatus.RUNNING)

        updated = await storage.update_task_status(
            task.id, TaskStatus.BLOCKED, blocked_reason="Need user input"
        )

        assert updated is not None
        assert updated.status == TaskStatus.BLOCKED
        assert updated.blocked_reason == "Need user input"

    @pytest.mark.asyncio
    async def test_update_task_status_failed(self, storage: SQLiteStorage):
        """Test updating task status to failed."""
        task = await storage.create_task(TaskCreate(title="Test"))
        await storage.update_task_status(task.id, TaskStatus.RUNNING)

        updated = await storage.update_task_status(
            task.id, TaskStatus.FAILED, error="Something went wrong"
        )

        assert updated is not None
        assert updated.status == TaskStatus.FAILED
        assert updated.error == "Something went wrong"


class TestAgents:
    """Tests for agent operations."""

    @pytest.mark.asyncio
    async def test_create_agent(self, storage: SQLiteStorage):
        """Test creating an agent record."""
        data = AgentRecordCreate(
            id="coder",
            name="Coder Agent",
            type="coder",
            config={"model": "claude-3-opus"},
        )
        agent = await storage.create_agent(data)

        assert agent.id == "coder"
        assert agent.name == "Coder Agent"
        assert agent.type == "coder"
        assert agent.status == AgentStatus.STOPPED
        assert agent.config == {"model": "claude-3-opus"}

    @pytest.mark.asyncio
    async def test_create_agent_updates_existing(self, storage: SQLiteStorage):
        """Test creating an agent with existing ID updates it."""
        data1 = AgentRecordCreate(id="test", name="Name 1", type="type1")
        await storage.create_agent(data1)

        data2 = AgentRecordCreate(id="test", name="Name 2", type="type2")
        agent = await storage.create_agent(data2)

        assert agent.name == "Name 2"
        assert agent.type == "type2"

    @pytest.mark.asyncio
    async def test_get_agent(self, storage: SQLiteStorage):
        """Test getting an agent by ID."""
        data = AgentRecordCreate(id="test", name="Test Agent", type="test")
        await storage.create_agent(data)

        agent = await storage.get_agent("test")
        assert agent is not None
        assert agent.id == "test"

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self, storage: SQLiteStorage):
        """Test getting a nonexistent agent returns None."""
        agent = await storage.get_agent("nonexistent")
        assert agent is None

    @pytest.mark.asyncio
    async def test_list_agents(self, storage: SQLiteStorage):
        """Test listing all agents."""
        await storage.create_agent(
            AgentRecordCreate(id="a", name="Agent A", type="test")
        )
        await storage.create_agent(
            AgentRecordCreate(id="b", name="Agent B", type="test")
        )

        agents = await storage.list_agents()
        assert len(agents) == 2

    @pytest.mark.asyncio
    async def test_update_agent_status(self, storage: SQLiteStorage):
        """Test updating agent status."""
        await storage.create_agent(
            AgentRecordCreate(id="test", name="Test", type="test")
        )

        updated = await storage.update_agent_status("test", AgentStatus.RUNNING)
        assert updated is not None
        assert updated.status == AgentStatus.RUNNING

    @pytest.mark.asyncio
    async def test_update_agent_heartbeat(self, storage: SQLiteStorage):
        """Test updating agent heartbeat."""
        await storage.create_agent(
            AgentRecordCreate(id="test", name="Test", type="test")
        )

        updated = await storage.update_agent_heartbeat("test")
        assert updated is not None
        assert updated.last_heartbeat is not None


class TestMemory:
    """Tests for memory operations."""

    @pytest.mark.asyncio
    async def test_create_memory(self, storage: SQLiteStorage):
        """Test creating a memory entry."""
        data = MemoryEntryCreate(
            content="User prefers dark mode",
            memory_type="preference",
            level="global",
        )
        memory = await storage.create_memory(data)

        assert memory.id is not None
        assert memory.content == "User prefers dark mode"
        assert memory.memory_type == "preference"
        assert memory.level == "global"

    @pytest.mark.asyncio
    async def test_create_memory_with_embedding(self, storage: SQLiteStorage):
        """Test creating a memory entry with embedding."""
        embedding = [0.1, 0.2, 0.3, 0.4, 0.5]
        data = MemoryEntryCreate(
            content="Test content",
            memory_type="fact",
            embedding=embedding,
        )
        memory = await storage.create_memory(data)

        assert memory.embedding == embedding

    @pytest.mark.asyncio
    async def test_create_memory_with_scope(self, storage: SQLiteStorage):
        """Test creating memory with project/agent scope."""
        data = MemoryEntryCreate(
            content="Project-specific memory",
            memory_type="fact",
            level="project",
            project_id="ungula",
            agent_id="coder",
        )
        memory = await storage.create_memory(data)

        assert memory.level == "project"
        assert memory.project_id == "ungula"
        assert memory.agent_id == "coder"

    @pytest.mark.asyncio
    async def test_get_memory(self, storage: SQLiteStorage):
        """Test getting a memory entry."""
        data = MemoryEntryCreate(content="Test", memory_type="fact")
        created = await storage.create_memory(data)

        retrieved = await storage.get_memory(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id

    @pytest.mark.asyncio
    async def test_get_memory_updates_access_tracking(self, storage: SQLiteStorage):
        """Test getting memory updates access count and time."""
        data = MemoryEntryCreate(content="Test", memory_type="fact")
        created = await storage.create_memory(data)
        initial_count = created.access_count

        await storage.get_memory(created.id)
        await storage.get_memory(created.id)

        retrieved = await storage.get_memory(created.id)
        assert retrieved is not None
        # Access count should be initial + 3 (each get increments)
        assert retrieved.access_count == initial_count + 3

    @pytest.mark.asyncio
    async def test_search_memory_by_type(self, storage: SQLiteStorage):
        """Test searching memory by type."""
        await storage.create_memory(
            MemoryEntryCreate(content="Pref 1", memory_type="preference")
        )
        await storage.create_memory(
            MemoryEntryCreate(content="Pref 2", memory_type="preference")
        )
        await storage.create_memory(
            MemoryEntryCreate(content="Fact 1", memory_type="fact")
        )

        prefs = await storage.search_memory(memory_type="preference")
        facts = await storage.search_memory(memory_type="fact")

        assert len(prefs) == 2
        assert len(facts) == 1

    @pytest.mark.asyncio
    async def test_search_memory_by_level(self, storage: SQLiteStorage):
        """Test searching memory by level."""
        await storage.create_memory(
            MemoryEntryCreate(content="Global", memory_type="fact", level="global")
        )
        await storage.create_memory(
            MemoryEntryCreate(
                content="Project",
                memory_type="fact",
                level="project",
                project_id="test",
            )
        )

        global_mems = await storage.search_memory(level="global")
        project_mems = await storage.search_memory(level="project")

        assert len(global_mems) == 1
        assert len(project_mems) == 1

    @pytest.mark.asyncio
    async def test_delete_memory(self, storage: SQLiteStorage):
        """Test deleting a memory entry."""
        data = MemoryEntryCreate(content="To delete", memory_type="fact")
        created = await storage.create_memory(data)

        result = await storage.delete_memory(created.id)
        assert result is True

        retrieved = await storage.get_memory(created.id)
        assert retrieved is None
