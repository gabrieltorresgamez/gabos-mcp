"""Tests for knowledge_read, knowledge_write, and knowledge_delete tools."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import pytest_asyncio

from gabos_mcp.extractors.agent_store import AgentStore
from gabos_mcp.extractors.knowledge import KnowledgeStore
from gabos_mcp.tools.knowledge import _assert_agent_tags_owned, register


def _make_mcp():
	"""Return a minimal FastMCP-like stub that captures registered tools."""

	class Stub:
		def __init__(self) -> None:
			self.tools: dict = {}
			self.resources: dict = {}

		def tool(self, fn):
			self.tools[fn.__name__] = fn
			return fn

		def resource(self, uri):
			def decorator(fn):
				self.resources[uri] = fn
				return fn

			return decorator

	return Stub()


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
async def tools(stores, tmp_path):
	ks, as_ = stores
	mcp = _make_mcp()
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


# ── knowledge_read ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestKnowledgeRead:
	async def test_list_mode_returns_visible_entries(self, tools):
		fns, ks, as_ = tools
		await ks.add(owner="alice", title="A", content="1", shared=True)
		await ks.add(owner="bob", title="B", content="2", shared=False)

		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(await fns["knowledge_read"]())
		titles = {e["title"] for e in result}
		assert "A" in titles
		assert "B" not in titles  # bob's private entry

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

	async def test_filter_by_tag(self, tools):
		fns, ks, as_ = tools
		await ks.add(owner="alice", title="Python", content="1", tags=["python"], shared=True)
		await ks.add(owner="alice", title="Go", content="2", tags=["go"], shared=True)
		with patch("gabos_mcp.tools.knowledge.get_github_login", return_value="alice"):
			result = json.loads(await fns["knowledge_read"](tag="python"))
		assert len(result) == 1
		assert result[0]["title"] == "Python"


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
