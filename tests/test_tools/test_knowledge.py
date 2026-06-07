"""Tests for knowledge_read, knowledge_write, and knowledge_delete tools."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import pytest_asyncio

from gabos_mcp.extractors.agent_store import AgentStore
from gabos_mcp.extractors.knowledge import KnowledgeStore
from gabos_mcp.tools.knowledge import _assert_agent_tags_owned, register


@pytest_asyncio.fixture
async def stores(tmp_path):
	ks = KnowledgeStore(db_path=str(tmp_path / "knowledge.db"))
	await ks.migrate()
	as_ = AgentStore(db_path=str(tmp_path / "agents.db"))
	await as_.migrate()
	yield ks, as_
	await ks.close()
	await as_.close()


@pytest_asyncio.fixture
async def tools(stores, tmp_path, make_mcp):
	ks, as_ = stores
	mcp = make_mcp()
	with (
		patch("gabos_mcp.tools.knowledge.get_knowledge_store", return_value=ks),
		patch("gabos_mcp.tools.knowledge.get_agent_store", return_value=as_),
	):
		register(mcp)
	return mcp.tools, ks, as_


# ── _assert_agent_tags_owned ────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAssertAgentTagsOwned:
	async def test_empty_tags_passes(self, stores):
		ks, as_ = stores
		await _assert_agent_tags_owned("alice", [], as_)  # no error

	async def test_non_agent_tags_pass(self, stores):
		ks, as_ = stores
		await _assert_agent_tags_owned("alice", ["python", "tips"], as_)  # no error

	async def test_owner_can_use_own_agent_tag(self, stores):
		ks, as_ = stores
		await as_.create(owner="alice", name="myagent", description="D", system_prompt="P")
		await _assert_agent_tags_owned("alice", ["agent:myagent"], as_)  # no error

	async def test_folder_tag_requires_ownership(self, stores):
		ks, as_ = stores
		await as_.create(owner="alice", name="myagent", description="D", system_prompt="P")
		with pytest.raises(PermissionError, match="agent:myagent"):
			await _assert_agent_tags_owned("bob", ["agent:myagent:folder:Tickets"], as_)

	async def test_non_owner_denied(self, stores):
		ks, as_ = stores
		await as_.create(owner="alice", name="myagent", description="D", system_prompt="P")
		with pytest.raises(PermissionError, match="agent:myagent"):
			await _assert_agent_tags_owned("bob", ["agent:myagent"], as_)

	async def test_missing_agent_denied(self, stores):
		ks, as_ = stores
		with pytest.raises(PermissionError, match="agent:ghost"):
			await _assert_agent_tags_owned("alice", ["agent:ghost"], as_)


# ── knowledge_search ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestKnowledgeSearch:
	async def test_returns_ranked_results(self, tools):
		fns, ks, as_ = tools
		await ks.add(owner="alice", title="Python tips", content="Use list comprehensions", shared=True)
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(await fns["knowledge_search"](query="Python"))
		assert len(result) == 1
		assert result[0]["title"] == "Python tips"

	async def test_returns_metadata_only_no_content(self, tools):
		fns, ks, as_ = tools
		await ks.add(owner="alice", title="Entry", content="secret content", shared=True)
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(await fns["knowledge_search"](query="Entry"))
		assert len(result) == 1
		hit = result[0]
		assert "content" not in hit
		assert "id" in hit
		assert "title" in hit
		assert "tags" in hit
		assert "owner" in hit
		assert "updated_at" in hit
		assert "score" in hit

	async def test_score_field_present(self, tools):
		fns, ks, as_ = tools
		await ks.add(owner="alice", title="SQLite notes", content="FTS5 trigram search", shared=True)
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(await fns["knowledge_search"](query="FTS5"))
		assert result[0]["score"] is not None

	async def test_filter_by_tag(self, tools):
		fns, ks, as_ = tools
		await ks.add(owner="alice", title="Python guide", content="comprehensions", tags=["python"], shared=True)
		await ks.add(owner="alice", title="Go guide", content="comprehensions", tags=["go"], shared=True)
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(await fns["knowledge_search"](query="comprehensions", tag="python"))
		assert len(result) == 1
		assert result[0]["title"] == "Python guide"

	async def test_filter_by_owner(self, tools):
		fns, ks, as_ = tools
		await ks.add(owner="alice", title="Alice tip", content="useful info", shared=True)
		await ks.add(owner="bob", title="Bob tip", content="useful info", shared=True)
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(await fns["knowledge_search"](query="useful", owner="alice"))
		assert all(r["owner"] == "alice" for r in result)
		titles = {r["title"] for r in result}
		assert "Alice tip" in titles
		assert "Bob tip" not in titles

	async def test_respects_visibility(self, tools):
		fns, ks, as_ = tools
		await ks.add(owner="alice", title="alice-private", content="secret data", shared=False)
		await ks.add(owner="alice", title="alice-shared", content="shared data", shared=True)
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="bob"):
			result = json.loads(await fns["knowledge_search"](query="data"))
		titles = {r["title"] for r in result}
		assert "alice-shared" in titles
		assert "alice-private" not in titles

	async def test_agent_tag_filter(self, tools):
		fns, ks, as_ = tools
		await as_.create(owner="alice", name="myagent", description="D", system_prompt="P")
		await ks.add(owner="alice", title="Agent fact", content="agent-specific info", tags=["agent:myagent"])
		await ks.add(owner="alice", title="General tip", content="agent-specific info", tags=["tips"])
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(await fns["knowledge_search"](query="info", tag="agent:myagent"))
		assert len(result) == 1
		assert result[0]["title"] == "Agent fact"

	async def test_pagination_via_limit(self, tools):
		fns, ks, as_ = tools
		for i in range(5):
			await ks.add(owner="alice", title=f"Entry {i}", content="common keyword here", shared=True)
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(await fns["knowledge_search"](query="keyword", limit=2))
		assert len(result) <= 2

	async def test_empty_query_returns_results(self, tools):
		fns, ks, as_ = tools
		await ks.add(owner="alice", title="Something", content="here", shared=True)
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			# empty/no-match query should not crash
			result = json.loads(await fns["knowledge_search"](query="xyzzy"))
		assert result == []


# ── knowledge_read ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestKnowledgeRead:
	async def test_fetch_by_id(self, tools):
		fns, ks, as_ = tools
		entry = await ks.add(owner="alice", title="T", content="Hello")
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(await fns["knowledge_read"](id=entry["id"]))
		assert result["title"] == "T"
		assert result["content"] == "Hello"

	async def test_cannot_fetch_other_private_entry(self, tools):
		fns, ks, as_ = tools
		entry = await ks.add(owner="alice", title="Secret", content="X", shared=False)
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="bob"), pytest.raises(PermissionError):
			await fns["knowledge_read"](id=entry["id"])

	async def test_not_found_raises_key_error(self, tools):
		fns, ks, as_ = tools
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"), pytest.raises(KeyError):
			await fns["knowledge_read"](id="nonexistent-id")


# ── knowledge_write ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestKnowledgeWrite:
	async def test_create_mode(self, tools):
		fns, ks, as_ = tools
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(await fns["knowledge_write"](mode="create", title="T", content="C"))
		assert result["title"] == "T"
		assert result["owner"] == "alice"

	async def test_create_requires_title(self, tools):
		fns, ks, as_ = tools
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(await fns["knowledge_write"](mode="create", content="C"))
		assert "error" in result

	async def test_create_requires_content(self, tools):
		fns, ks, as_ = tools
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(await fns["knowledge_write"](mode="create", title="T"))
		assert "error" in result

	async def test_create_rejects_id(self, tools):
		fns, ks, as_ = tools
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(await fns["knowledge_write"](mode="create", id="x", title="T", content="C"))
		assert "error" in result

	async def test_update_mode(self, tools):
		fns, ks, as_ = tools
		entry = await ks.add(owner="alice", title="Old", content="C")
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(await fns["knowledge_write"](mode="update", id=entry["id"], title="New"))
		assert result["title"] == "New"
		assert result["content"] == "C"  # preserved

	async def test_update_preserves_shared_when_omitted(self, tools):
		fns, ks, as_ = tools
		entry = await ks.add(owner="alice", title="T", content="C", shared=True)
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(await fns["knowledge_write"](mode="update", id=entry["id"], title="New"))
		assert result["shared"] is True  # must not be silently reset to False

	async def test_update_requires_id(self, tools):
		fns, ks, as_ = tools
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(await fns["knowledge_write"](mode="update", title="X"))
		assert "error" in result

	async def test_update_owner_only(self, tools):
		fns, ks, as_ = tools
		entry = await ks.add(owner="alice", title="T", content="C")
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="bob"), pytest.raises(PermissionError):
			await fns["knowledge_write"](mode="update", id=entry["id"], title="X")

	async def test_create_with_agent_tag_requires_ownership(self, tools):
		fns, ks, as_ = tools
		await as_.create(owner="alice", name="myagent", description="D", system_prompt="P")
		with (
			patch("gabos_mcp.tools.knowledge.get_github_login", return_value="bob"),
			pytest.raises(PermissionError, match="agent:myagent"),
		):
			await fns["knowledge_write"](mode="create", title="T", content="C", tags=["agent:myagent"])

	async def test_update_with_agent_tag_requires_ownership(self, tools):
		fns, ks, as_ = tools
		await as_.create(owner="alice", name="myagent", description="D", system_prompt="P")
		entry = await ks.add(owner="bob", title="T", content="C")
		with (
			patch("gabos_mcp.tools.knowledge.get_github_login", return_value="bob"),
			pytest.raises(PermissionError, match="agent:myagent"),
		):
			await fns["knowledge_write"](mode="update", id=entry["id"], tags=["agent:myagent"])

	async def test_owner_can_use_own_agent_tag(self, tools):
		fns, ks, as_ = tools
		await as_.create(owner="alice", name="myagent", description="D", system_prompt="P")
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(
				await fns["knowledge_write"](mode="create", title="T", content="C", tags=["agent:myagent"])
			)
		assert "agent:myagent" in result["tags"]

	async def test_anon_denied(self, tools):
		fns, ks, as_ = tools
		with (
			patch("gabos_mcp.tools.knowledge.get_github_login", return_value="anonymous"),
			pytest.raises(PermissionError),
		):
			await fns["knowledge_write"](mode="create", title="T", content="C")


# ── knowledge_delete ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestKnowledgeDelete:
	async def test_owner_can_delete(self, tools):
		fns, ks, as_ = tools
		entry = await ks.add(owner="alice", title="T", content="C")
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(await fns["knowledge_delete"](id=entry["id"]))
		assert result["deleted"] == entry["id"]
		assert await ks.get(entry["id"]) is None

	async def test_non_owner_denied(self, tools):
		fns, ks, as_ = tools
		entry = await ks.add(owner="alice", title="T", content="C", shared=True)
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="bob"), pytest.raises(PermissionError):
			await fns["knowledge_delete"](id=entry["id"])

	async def test_agent_owner_cannot_delete_others_shared_knowledge(self, tools):
		"""Non-owner can no longer delete shared knowledge even if tagged to their agent."""
		fns, ks, as_ = tools
		await as_.create(owner="bob", name="myagent", description="D", system_prompt="P")
		entry = await ks.add(owner="alice", title="T", content="C", tags=["agent:myagent"], shared=True)
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="bob"), pytest.raises(PermissionError):
			await fns["knowledge_delete"](id=entry["id"])
