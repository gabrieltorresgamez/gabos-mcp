import pytest
import pytest_asyncio

from gabos_mcp.extractors.agent_store import AgentStore


@pytest_asyncio.fixture
async def store(tmp_path):
	s = AgentStore(db_path=str(tmp_path / "agents.db"))
	await s.migrate()
	yield s
	await s.close()


@pytest.mark.asyncio
class TestAgentCreate:
	async def test_creates_with_required_fields(self, store):
		agent = await store.create(
			owner="alice", name="test", description="A test agent", system_prompt="You are helpful."
		)
		assert agent.id
		assert agent.owner == "alice"
		assert agent.name == "test"
		assert agent.description == "A test agent"
		assert agent.system_prompt == "You are helpful."
		assert agent.model == AgentStore.DEFAULT_MODEL
		assert agent.knowledge_tags == []
		assert agent.shared is False

	async def test_creates_with_all_fields(self, store):
		agent = await store.create(
			owner="alice",
			name="full",
			description="Full agent",
			system_prompt="Prompt",
			model="claude-sonnet-4-6",
			knowledge_tags=["tag1", "tag2"],
			shared=True,
		)
		assert agent.model == "claude-sonnet-4-6"
		assert agent.knowledge_tags == ["tag1", "tag2"]
		assert agent.shared is True

	async def test_raises_on_duplicate_name(self, store):
		await store.create(owner="alice", name="dup", description="D", system_prompt="P")
		with pytest.raises(ValueError, match="already exists"):
			await store.create(owner="bob", name="dup", description="D2", system_prompt="P2")


@pytest.mark.asyncio
class TestAgentGet:
	async def test_get_by_name(self, store):
		created = await store.create(owner="alice", name="myagent", description="D", system_prompt="P")
		found = await store.get("myagent")
		assert found is not None
		assert found.id == created.id

	async def test_get_by_id(self, store):
		created = await store.create(owner="alice", name="myagent", description="D", system_prompt="P")
		found = await store.get(created.id)
		assert found is not None
		assert found.name == "myagent"

	async def test_returns_none_for_missing(self, store):
		assert await store.get("nonexistent") is None


@pytest.mark.asyncio
class TestAgentList:
	async def test_returns_all_agents_without_caller(self, store):
		await store.create(owner="alice", name="a", description="D", system_prompt="P")
		await store.create(owner="bob", name="b", description="D", system_prompt="P")
		agents = await store.list_agents()
		assert len(agents) == 2

	async def test_caller_sees_own_and_shared(self, store):
		await store.create(owner="alice", name="alice-private", description="D", system_prompt="P", shared=False)
		await store.create(owner="alice", name="alice-shared", description="D", system_prompt="P", shared=True)
		await store.create(owner="bob", name="bob-private", description="D", system_prompt="P", shared=False)
		await store.create(owner="bob", name="bob-shared", description="D", system_prompt="P", shared=True)

		alice_view = await store.list_agents(caller="alice")
		names = {a.name for a in alice_view}
		assert "alice-private" in names
		assert "alice-shared" in names
		assert "bob-shared" in names
		assert "bob-private" not in names

	async def test_ordered_by_name(self, store):
		await store.create(owner="alice", name="zebra", description="D", system_prompt="P")
		await store.create(owner="alice", name="alpha", description="D", system_prompt="P")
		agents = await store.list_agents()
		assert agents[0].name == "alpha"
		assert agents[1].name == "zebra"

	async def test_empty(self, store):
		assert await store.list_agents() == []


@pytest.mark.asyncio
class TestAgentUpdate:
	async def test_owner_can_update_description(self, store):
		await store.create(owner="alice", name="ag", description="Old", system_prompt="P")
		updated = await store.update("ag", owner="alice", description="New")
		assert updated.description == "New"
		assert updated.system_prompt == "P"

	async def test_owner_can_update_shared_flag(self, store):
		await store.create(owner="alice", name="ag", description="D", system_prompt="P", shared=False)
		updated = await store.update("ag", owner="alice", shared=True)
		assert updated.shared is True

	async def test_non_owner_cannot_update(self, store):
		await store.create(owner="alice", name="ag", description="D", system_prompt="P")
		with pytest.raises(PermissionError, match="only edit your own"):
			await store.update("ag", owner="bob", description="X")

	async def test_partial_update_knowledge_tags(self, store):
		await store.create(owner="alice", name="ag", description="D", system_prompt="P")
		updated = await store.update("ag", owner="alice", knowledge_tags=["t1", "t2"])
		assert updated.knowledge_tags == ["t1", "t2"]

	async def test_raises_on_missing_agent(self, store):
		with pytest.raises(KeyError, match="not found"):
			await store.update("ghost", owner="alice", description="X")


@pytest.mark.asyncio
class TestAgentDelete:
	async def test_owner_can_delete(self, store):
		await store.create(owner="alice", name="ag", description="D", system_prompt="P")
		await store.delete("ag", owner="alice")
		assert await store.get("ag") is None

	async def test_non_owner_cannot_delete(self, store):
		await store.create(owner="alice", name="ag", description="D", system_prompt="P")
		with pytest.raises(PermissionError, match="only delete your own"):
			await store.delete("ag", owner="bob")

	async def test_raises_on_missing(self, store):
		with pytest.raises(KeyError, match="not found"):
			await store.delete("ghost", owner="alice")


@pytest.mark.asyncio
class TestGetMany:
	async def test_returns_agents_by_name(self, store):
		await store.create(owner="alice", name="a1", description="D", system_prompt="P")
		await store.create(owner="bob", name="a2", description="D", system_prompt="P")
		result = await store.get_many(["a1", "a2"])
		assert set(result.keys()) == {"a1", "a2"}
		assert result["a1"].owner == "alice"
		assert result["a2"].owner == "bob"

	async def test_returns_empty_for_no_names(self, store):
		result = await store.get_many([])
		assert result == {}

	async def test_ignores_missing_names(self, store):
		await store.create(owner="alice", name="real", description="D", system_prompt="P")
		result = await store.get_many(["real", "ghost"])
		assert "real" in result
		assert "ghost" not in result
