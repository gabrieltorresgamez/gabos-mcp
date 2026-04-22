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
		assert agent.auto_learn is True

	async def test_creates_with_all_fields(self, store):
		agent = await store.create(
			owner="alice",
			name="full",
			description="Full agent",
			system_prompt="Prompt",
			model="claude-sonnet-4-6",
			knowledge_tags=["tag1", "tag2"],
			auto_learn=False,
		)
		assert agent.model == "claude-sonnet-4-6"
		assert agent.knowledge_tags == ["tag1", "tag2"]
		assert agent.auto_learn is False

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
	async def test_returns_all_agents(self, store):
		await store.create(owner="alice", name="a", description="D", system_prompt="P")
		await store.create(owner="bob", name="b", description="D", system_prompt="P")
		agents = await store.list_agents()
		assert len(agents) == 2

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

	async def test_cascades_to_doc_refs(self, store):
		agent = await store.create(owner="alice", name="ag", description="D", system_prompt="P")
		await store.add_doc_ref(agent.name, "_global", "APP", "src", "path/page")
		await store.delete("ag", owner="alice")
		with pytest.raises(KeyError):
			await store.list_doc_refs("ag")


@pytest.mark.asyncio
class TestDocRefs:
	async def test_add_and_list(self, store):
		await store.create(owner="alice", name="ag", description="D", system_prompt="P")
		ref = await store.add_doc_ref("ag", "_global", "APP", "src", "path/page", "Relevant because X")
		assert ref.id
		assert ref.context_key == "_global"
		assert ref.app == "APP"
		assert ref.relevance_note == "Relevant because X"

		refs = await store.list_doc_refs("ag")
		assert len(refs) == 1
		assert refs[0].id == ref.id

	async def test_owner_enforced_on_add(self, store):
		await store.create(owner="alice", name="ag", description="D", system_prompt="P")
		with pytest.raises(PermissionError, match="only add doc refs"):
			await store.add_doc_ref("ag", "_global", "APP", "src", "page", owner="bob")

	async def test_filter_by_context_keys(self, store):
		await store.create(owner="alice", name="ag", description="D", system_prompt="P")
		await store.add_doc_ref("ag", "_global", "APP", "src", "global-page")
		await store.add_doc_ref("ag", "Tickets", "APP", "src", "tickets-page")
		await store.add_doc_ref("ag", "Changes", "APP", "src", "changes-page")

		refs = await store.list_doc_refs("ag", context_keys=["_global", "Tickets"])
		paths = {r.page_path for r in refs}
		assert "global-page" in paths
		assert "tickets-page" in paths
		assert "changes-page" not in paths

	async def test_raises_on_duplicate_ref(self, store):
		await store.create(owner="alice", name="ag", description="D", system_prompt="P")
		await store.add_doc_ref("ag", "_global", "APP", "src", "page")
		with pytest.raises(ValueError, match="already exists"):
			await store.add_doc_ref("ag", "_global", "APP", "src", "page")

	async def test_delete_doc_ref(self, store):
		await store.create(owner="alice", name="ag", description="D", system_prompt="P")
		ref = await store.add_doc_ref("ag", "_global", "APP", "src", "page")
		await store.delete_doc_ref(ref.id, owner="alice")
		refs = await store.list_doc_refs("ag")
		assert refs == []

	async def test_non_owner_cannot_delete_doc_ref(self, store):
		await store.create(owner="alice", name="ag", description="D", system_prompt="P")
		ref = await store.add_doc_ref("ag", "_global", "APP", "src", "page")
		with pytest.raises(PermissionError, match="only delete doc refs"):
			await store.delete_doc_ref(ref.id, owner="bob")

	async def test_delete_doc_ref_raises_on_missing(self, store):
		with pytest.raises(KeyError, match="not found"):
			await store.delete_doc_ref("bad-id")

	async def test_raises_on_unknown_agent(self, store):
		with pytest.raises(KeyError, match="not found"):
			await store.add_doc_ref("ghost", "_global", "APP", "src", "page")
