import pytest
import pytest_asyncio

from gabos_mcp.extractors.knowledge import KnowledgeStore


@pytest_asyncio.fixture
async def store(tmp_path):
	s = KnowledgeStore(db_path=str(tmp_path / "knowledge.db"))
	await s.migrate()
	return s


@pytest.mark.asyncio
class TestAdd:
	async def test_returns_entry_with_all_fields(self, store):
		entry = await store.add(owner="alice", title="My Note", content="Hello world")
		assert entry["id"]
		assert entry["owner"] == "alice"
		assert entry["title"] == "My Note"
		assert entry["content"] == "Hello world"
		assert entry["tags"] == []
		assert entry["created_at"]
		assert entry["updated_at"]

	async def test_stores_tags(self, store):
		entry = await store.add(owner="alice", title="T", content="C", tags=["python", "tips"])
		assert entry["tags"] == ["python", "tips"]

	async def test_persists_to_db(self, store):
		entry = await store.add(owner="alice", title="T", content="C")
		fetched = await store.get(entry["id"])
		assert fetched is not None
		assert fetched["title"] == "T"


@pytest.mark.asyncio
class TestGet:
	async def test_returns_none_for_missing(self, store):
		assert await store.get("nonexistent-id") is None

	async def test_returns_entry(self, store):
		entry = await store.add(owner="alice", title="T", content="C")
		fetched = await store.get(entry["id"])
		assert fetched == entry


@pytest.mark.asyncio
class TestList:
	async def test_returns_all_entries(self, store):
		await store.add(owner="alice", title="A", content="1")
		await store.add(owner="bob", title="B", content="2")
		assert len(await store.list_entries()) == 2

	async def test_filter_by_owner(self, store):
		await store.add(owner="alice", title="A", content="1")
		await store.add(owner="bob", title="B", content="2")
		results = await store.list_entries(owner="alice")
		assert len(results) == 1
		assert results[0]["owner"] == "alice"

	async def test_filter_by_tag(self, store):
		await store.add(owner="alice", title="A", content="1", tags=["python"])
		await store.add(owner="bob", title="B", content="2", tags=["go"])
		results = await store.list_entries(tag="python")
		assert len(results) == 1
		assert results[0]["owner"] == "alice"

	async def test_pagination(self, store):
		for i in range(5):
			await store.add(owner="alice", title=f"T{i}", content="C")
		page1 = await store.list_entries(limit=2, offset=0)
		page2 = await store.list_entries(limit=2, offset=2)
		assert len(page1) == 2
		assert len(page2) == 2
		assert {r["title"] for r in page1}.isdisjoint({r["title"] for r in page2})

	async def test_empty_list(self, store):
		assert await store.list_entries() == []


@pytest.mark.asyncio
class TestUpdate:
	async def test_updates_title(self, store):
		entry = await store.add(owner="alice", title="Old", content="C")
		updated = await store.update(id=entry["id"], owner="alice", title="New")
		assert updated["title"] == "New"
		assert updated["content"] == "C"

	async def test_updates_content(self, store):
		entry = await store.add(owner="alice", title="T", content="Old")
		updated = await store.update(id=entry["id"], owner="alice", content="New")
		assert updated["content"] == "New"

	async def test_updates_tags(self, store):
		entry = await store.add(owner="alice", title="T", content="C", tags=["a"])
		updated = await store.update(id=entry["id"], owner="alice", tags=["b", "c"])
		assert updated["tags"] == ["b", "c"]

	async def test_partial_update_preserves_other_fields(self, store):
		entry = await store.add(owner="alice", title="T", content="C", tags=["x"])
		updated = await store.update(id=entry["id"], owner="alice", title="New T")
		assert updated["content"] == "C"
		assert updated["tags"] == ["x"]

	async def test_persists_update(self, store):
		entry = await store.add(owner="alice", title="T", content="C")
		await store.update(id=entry["id"], owner="alice", title="Updated")
		fetched = await store.get(entry["id"])
		assert fetched is not None
		assert fetched["title"] == "Updated"

	async def test_raises_on_missing_entry(self, store):
		with pytest.raises(KeyError, match="not found"):
			await store.update(id="bad-id", owner="alice", title="X")

	async def test_raises_on_wrong_owner(self, store):
		entry = await store.add(owner="alice", title="T", content="C")
		with pytest.raises(PermissionError, match="only edit your own"):
			await store.update(id=entry["id"], owner="bob", title="X")


@pytest.mark.asyncio
class TestDelete:
	async def test_deletes_entry(self, store):
		entry = await store.add(owner="alice", title="T", content="C")
		await store.delete(id=entry["id"], owner="alice")
		assert await store.get(entry["id"]) is None

	async def test_raises_on_missing_entry(self, store):
		with pytest.raises(KeyError, match="not found"):
			await store.delete(id="bad-id", owner="alice")

	async def test_raises_on_wrong_owner(self, store):
		entry = await store.add(owner="alice", title="T", content="C")
		with pytest.raises(PermissionError, match="only delete your own"):
			await store.delete(id=entry["id"], owner="bob")
