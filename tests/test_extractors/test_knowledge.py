import pytest

from gabos_mcp.extractors.knowledge import KnowledgeStore


@pytest.fixture
def store(tmp_path):
	return KnowledgeStore(db_path=str(tmp_path / "knowledge.db"))


class TestAdd:
	def test_returns_entry_with_all_fields(self, store):
		entry = store.add(owner="alice", title="My Note", content="Hello world")
		assert entry["id"]
		assert entry["owner"] == "alice"
		assert entry["title"] == "My Note"
		assert entry["content"] == "Hello world"
		assert entry["tags"] == []
		assert entry["created_at"]
		assert entry["updated_at"]

	def test_stores_tags(self, store):
		entry = store.add(owner="alice", title="T", content="C", tags=["python", "tips"])
		assert entry["tags"] == ["python", "tips"]

	def test_persists_to_db(self, store):
		entry = store.add(owner="alice", title="T", content="C")
		fetched = store.get(entry["id"])
		assert fetched is not None
		assert fetched["title"] == "T"


class TestGet:
	def test_returns_none_for_missing(self, store):
		assert store.get("nonexistent-id") is None

	def test_returns_entry(self, store):
		entry = store.add(owner="alice", title="T", content="C")
		fetched = store.get(entry["id"])
		assert fetched == entry


class TestList:
	def test_returns_all_entries(self, store):
		store.add(owner="alice", title="A", content="1")
		store.add(owner="bob", title="B", content="2")
		assert len(store.list_entries()) == 2

	def test_filter_by_owner(self, store):
		store.add(owner="alice", title="A", content="1")
		store.add(owner="bob", title="B", content="2")
		results = store.list_entries(owner="alice")
		assert len(results) == 1
		assert results[0]["owner"] == "alice"

	def test_filter_by_tag(self, store):
		store.add(owner="alice", title="A", content="1", tags=["python"])
		store.add(owner="bob", title="B", content="2", tags=["go"])
		results = store.list_entries(tag="python")
		assert len(results) == 1
		assert results[0]["owner"] == "alice"

	def test_pagination(self, store):
		for i in range(5):
			store.add(owner="alice", title=f"T{i}", content="C")
		page1 = store.list_entries(limit=2, offset=0)
		page2 = store.list_entries(limit=2, offset=2)
		assert len(page1) == 2
		assert len(page2) == 2
		assert {r["title"] for r in page1}.isdisjoint({r["title"] for r in page2})

	def test_empty_list(self, store):
		assert store.list_entries() == []


class TestUpdate:
	def test_updates_title(self, store):
		entry = store.add(owner="alice", title="Old", content="C")
		updated = store.update(id=entry["id"], owner="alice", title="New")
		assert updated["title"] == "New"
		assert updated["content"] == "C"

	def test_updates_content(self, store):
		entry = store.add(owner="alice", title="T", content="Old")
		updated = store.update(id=entry["id"], owner="alice", content="New")
		assert updated["content"] == "New"

	def test_updates_tags(self, store):
		entry = store.add(owner="alice", title="T", content="C", tags=["a"])
		updated = store.update(id=entry["id"], owner="alice", tags=["b", "c"])
		assert updated["tags"] == ["b", "c"]

	def test_partial_update_preserves_other_fields(self, store):
		entry = store.add(owner="alice", title="T", content="C", tags=["x"])
		updated = store.update(id=entry["id"], owner="alice", title="New T")
		assert updated["content"] == "C"
		assert updated["tags"] == ["x"]

	def test_persists_update(self, store):
		entry = store.add(owner="alice", title="T", content="C")
		store.update(id=entry["id"], owner="alice", title="Updated")
		fetched = store.get(entry["id"])
		assert fetched is not None
		assert fetched["title"] == "Updated"

	def test_raises_on_missing_entry(self, store):
		with pytest.raises(KeyError, match="not found"):
			store.update(id="bad-id", owner="alice", title="X")

	def test_raises_on_wrong_owner(self, store):
		entry = store.add(owner="alice", title="T", content="C")
		with pytest.raises(PermissionError, match="only edit your own"):
			store.update(id=entry["id"], owner="bob", title="X")


class TestDelete:
	def test_deletes_entry(self, store):
		entry = store.add(owner="alice", title="T", content="C")
		store.delete(id=entry["id"], owner="alice")
		assert store.get(entry["id"]) is None

	def test_raises_on_missing_entry(self, store):
		with pytest.raises(KeyError, match="not found"):
			store.delete(id="bad-id", owner="alice")

	def test_raises_on_wrong_owner(self, store):
		entry = store.add(owner="alice", title="T", content="C")
		with pytest.raises(PermissionError, match="only delete your own"):
			store.delete(id=entry["id"], owner="bob")
