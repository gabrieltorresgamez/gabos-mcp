"""Tests for agent_read, agent_write, agent_delete tools."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import pytest_asyncio

from gabos_mcp.extractors.agent_store import AgentStore
from gabos_mcp.extractors.chm import ChmExtractor
from gabos_mcp.extractors.knowledge import KnowledgeStore
from gabos_mcp.tools.agents import register


def _make_mcp():
	class Stub:
		def __init__(self) -> None:
			self.tools: dict = {}

		def tool(self, fn):
			self.tools[fn.__name__] = fn
			return fn

	return Stub()


@pytest_asyncio.fixture
async def stores(tmp_path):
	as_ = AgentStore(db_path=str(tmp_path / "agents.db"))
	await as_.migrate()
	ks = KnowledgeStore(db_path=str(tmp_path / "knowledge.db"))
	await ks.migrate()
	yield as_, ks
	await as_.close()
	await ks.close()


@pytest_asyncio.fixture
async def tools(stores, tmp_path):
	as_, ks = stores
	chm = ChmExtractor(apps={}, cache_dir=str(tmp_path / "chm"))
	mcp = _make_mcp()
	with (
		patch("gabos_mcp.tools.agents.get_agent_store", return_value=as_),
		patch("gabos_mcp.tools.agents.get_knowledge_store", return_value=ks),
		patch("gabos_mcp.tools.agents.ChmExtractor", return_value=chm),
	):
		register(mcp)
	return mcp.tools, as_, ks


# ── agent_read ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAgentRead:
	async def test_list_mode_returns_visible_agents(self, tools):
		fns, as_, ks = tools
		await as_.create(owner="alice", name="alice-private", description="D", system_prompt="P", shared=False)
		await as_.create(owner="alice", name="alice-shared", description="D", system_prompt="P", shared=True)
		await as_.create(owner="bob", name="bob-private", description="D", system_prompt="P", shared=False)

		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_read"]())
		names = {a["name"] for a in result}
		assert "alice-private" in names
		assert "alice-shared" in names
		assert "bob-private" not in names

	async def test_fetch_by_name(self, tools):
		fns, as_, ks = tools
		await as_.create(owner="alice", name="myagent", description="D", system_prompt="P")
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_read"](name_or_id="myagent"))
		assert result["name"] == "myagent"
		assert "system_prompt" in result

	async def test_non_owner_cannot_fetch_private_agent(self, tools):
		fns, as_, ks = tools
		await as_.create(owner="alice", name="private", description="D", system_prompt="P", shared=False)
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="bob"), pytest.raises(PermissionError):
			await fns["agent_read"](name_or_id="private")

	async def test_include_doc_refs(self, tools):
		fns, as_, ks = tools
		agent = await as_.create(owner="alice", name="ag", description="D", system_prompt="P")
		await as_.add_doc_ref(agent.name, "_global", "APP", "src", "page.md", caller="alice")
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_read"](name_or_id="ag", include_doc_refs=True))
		assert "doc_refs" in result
		assert len(result["doc_refs"]) == 1

	async def test_doc_refs_filtered_by_context_key(self, tools):
		fns, as_, ks = tools
		agent = await as_.create(owner="alice", name="ag", description="D", system_prompt="P")
		await as_.add_doc_ref(agent.name, "_global", "APP", "src", "global.md", caller="alice")
		await as_.add_doc_ref(agent.name, "Tickets", "APP", "src", "tickets.md", caller="alice")
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(
				await fns["agent_read"](name_or_id="ag", include_doc_refs=True, doc_ref_context_key="Tickets")
			)
		paths = {r["page_path"] for r in result["doc_refs"]}
		assert "tickets.md" in paths
		assert "global.md" not in paths


# ── agent_write ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAgentWrite:
	async def test_create_mode(self, tools):
		fns, as_, ks = tools
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(
				await fns["agent_write"](mode="create", name="myagent", description="D", system_prompt="P")
			)
		assert result["name"] == "myagent"
		assert result["owner"] == "alice"

	async def test_create_requires_name(self, tools):
		fns, as_, ks = tools
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_write"](mode="create", description="D", system_prompt="P"))
		assert "error" in result

	async def test_create_requires_description(self, tools):
		fns, as_, ks = tools
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_write"](mode="create", name="n", system_prompt="P"))
		assert "error" in result

	async def test_create_requires_system_prompt(self, tools):
		fns, as_, ks = tools
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_write"](mode="create", name="n", description="D"))
		assert "error" in result

	async def test_update_mode(self, tools):
		fns, as_, ks = tools
		await as_.create(owner="alice", name="ag", description="Old", system_prompt="P")
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_write"](mode="update", name_or_id="ag", description="New"))
		assert result["description"] == "New"

	async def test_update_owner_only(self, tools):
		fns, as_, ks = tools
		await as_.create(owner="alice", name="ag", description="D", system_prompt="P")
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="bob"), pytest.raises(PermissionError):
			await fns["agent_write"](mode="update", name_or_id="ag", description="X")

	async def test_update_requires_name_or_id(self, tools):
		fns, as_, ks = tools
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_write"](mode="update", description="X"))
		assert "error" in result

	async def test_create_with_doc_refs(self, tools):
		fns, as_, ks = tools
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(
				await fns["agent_write"](
					mode="create",
					name="ag",
					description="D",
					system_prompt="P",
					doc_refs=[{"context_key": "_global", "app": "APP", "source": "src", "page_path": "page.md"}],
				)
			)
		assert "doc_refs_added" in result
		assert len(result["doc_refs_added"]) == 1

	async def test_create_with_learnings(self, tools):
		fns, as_, ks = tools
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(
				await fns["agent_write"](
					mode="create",
					name="ag",
					description="D",
					system_prompt="P",
					learnings=[{"title": "A fact", "content": "Fact content"}],
				)
			)
		assert "learnings_saved" in result
		entries = await ks.list_entries(tag="agent:ag")
		assert len(entries) == 1
		assert "agent:ag" in entries[0]["tags"]

	async def test_update_doc_refs_additive(self, tools):
		fns, as_, ks = tools
		await as_.create(owner="alice", name="ag", description="D", system_prompt="P")
		await as_.add_doc_ref("ag", "_global", "APP", "src", "existing.md", caller="alice")
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			await fns["agent_write"](
				mode="update",
				name_or_id="ag",
				doc_refs=[{"context_key": "_global", "app": "APP", "source": "src", "page_path": "new.md"}],
			)
		refs = await as_.list_doc_refs("ag")
		paths = {r.page_path for r in refs}
		assert "existing.md" in paths
		assert "new.md" in paths

	async def test_duplicate_doc_refs_skipped(self, tools):
		fns, as_, ks = tools
		await as_.create(owner="alice", name="ag", description="D", system_prompt="P")
		await as_.add_doc_ref("ag", "_global", "APP", "src", "page.md", caller="alice")
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(
				await fns["agent_write"](
					mode="update",
					name_or_id="ag",
					doc_refs=[{"context_key": "_global", "app": "APP", "source": "src", "page_path": "page.md"}],
				)
			)
		assert "page.md" in str(result.get("doc_refs_skipped_duplicates", []))

	async def test_anon_denied(self, tools):
		fns, as_, ks = tools
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="anonymous"), pytest.raises(PermissionError):
			await fns["agent_write"](mode="create", name="n", description="D", system_prompt="P")


# ── agent_delete ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAgentDelete:
	async def test_owner_can_delete_agent(self, tools):
		fns, as_, ks = tools
		await as_.create(owner="alice", name="ag", description="D", system_prompt="P")
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_delete"](name_or_id="ag"))
		assert result["deleted"] == "ag"
		assert await as_.get("ag") is None

	async def test_non_owner_denied(self, tools):
		fns, as_, ks = tools
		await as_.create(owner="alice", name="ag", description="D", system_prompt="P")
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="bob"), pytest.raises(PermissionError):
			await fns["agent_delete"](name_or_id="ag")

	async def test_delete_specific_doc_refs(self, tools):
		fns, as_, ks = tools
		await as_.create(owner="alice", name="ag", description="D", system_prompt="P")
		ref1 = await as_.add_doc_ref("ag", "_global", "APP", "src", "p1.md", caller="alice")
		ref2 = await as_.add_doc_ref("ag", "_global", "APP", "src", "p2.md", caller="alice")
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_delete"](name_or_id="ag", doc_ref_ids=[ref1.id]))
		assert ref1.id in result["deleted_doc_refs"]
		# agent still exists
		assert await as_.get("ag") is not None
		# ref2 still present
		refs = await as_.list_doc_refs("ag")
		assert any(r.id == ref2.id for r in refs)

	async def test_delete_doc_ref_non_owner_denied(self, tools):
		fns, as_, ks = tools
		await as_.create(owner="alice", name="ag", description="D", system_prompt="P")
		ref = await as_.add_doc_ref("ag", "_global", "APP", "src", "p.md", caller="alice")
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="bob"):
			result = json.loads(await fns["agent_delete"](name_or_id="ag", doc_ref_ids=[ref.id]))
		assert result.get("errors")

	async def test_anon_denied(self, tools):
		fns, as_, ks = tools
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="anonymous"), pytest.raises(PermissionError):
			await fns["agent_delete"](name_or_id="ag")
