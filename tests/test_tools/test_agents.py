"""Tests for agent_read, agent_write, agent_delete tools."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import pytest_asyncio

from gabos_mcp.extractors.agent_store import AgentStore
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
	mcp = _make_mcp()
	with (
		patch("gabos_mcp.tools.agents.get_agent_store", return_value=as_),
	):
		register(mcp)
	return mcp.tools, as_, ks


# ── agent_search ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAgentSearch:
	async def test_lists_visible_agents(self, tools):
		fns, as_, ks = tools
		await as_.create(owner="alice", name="alice-private", description="D", system_prompt="P", shared=False)
		await as_.create(owner="alice", name="alice-shared", description="D", system_prompt="P", shared=True)
		await as_.create(owner="bob", name="bob-private", description="D", system_prompt="P", shared=False)

		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_search"]())
		names = {a["name"] for a in result}
		assert "alice-private" in names
		assert "alice-shared" in names
		assert "bob-private" not in names

	async def test_result_includes_id(self, tools):
		fns, as_, ks = tools
		await as_.create(owner="alice", name="myagent", description="D", system_prompt="P")
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_search"]())
		assert all("id" in a for a in result)

	async def test_query_filters_by_name(self, tools):
		fns, as_, ks = tools
		await as_.create(owner="alice", name="omnitracker", description="D", system_prompt="P", shared=True)
		await as_.create(owner="alice", name="helpdesk", description="D", system_prompt="P", shared=True)
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_search"](query="omni"))
		assert len(result) == 1
		assert result[0]["name"] == "omnitracker"

	async def test_query_filters_by_description(self, tools):
		fns, as_, ks = tools
		await as_.create(owner="alice", name="ag", description="ticket management", system_prompt="P", shared=True)
		await as_.create(owner="alice", name="bg", description="unrelated", system_prompt="P", shared=True)
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_search"](query="ticket"))
		assert len(result) == 1
		assert result[0]["name"] == "ag"


# ── agent_read ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAgentRead:
	async def test_fetch_by_id(self, tools):
		fns, as_, ks = tools
		agent = await as_.create(owner="alice", name="myagent", description="D", system_prompt="P")
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_read"](id=agent.id))
		assert result["name"] == "myagent"
		assert "system_prompt" in result

	async def test_name_lookup_not_supported(self, tools):
		fns, as_, ks = tools
		await as_.create(owner="alice", name="myagent", description="D", system_prompt="P")
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"), pytest.raises(KeyError):
			await fns["agent_read"](id="myagent")

	async def test_non_owner_cannot_fetch_private_agent(self, tools):
		fns, as_, ks = tools
		agent = await as_.create(owner="alice", name="private", description="D", system_prompt="P", shared=False)
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="bob"), pytest.raises(PermissionError):
			await fns["agent_read"](id=agent.id)

	async def test_shared_agent_visible_to_non_owner(self, tools):
		fns, as_, ks = tools
		agent = await as_.create(owner="alice", name="shared", description="D", system_prompt="P", shared=True)
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="bob"):
			result = json.loads(await fns["agent_read"](id=agent.id))
		assert result["name"] == "shared"


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
		agent = await as_.create(owner="alice", name="ag", description="Old", system_prompt="P")
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_write"](mode="update", id=agent.id, description="New"))
		assert result["description"] == "New"

	async def test_update_owner_only(self, tools):
		fns, as_, ks = tools
		agent = await as_.create(owner="alice", name="ag", description="D", system_prompt="P")
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="bob"), pytest.raises(PermissionError):
			await fns["agent_write"](mode="update", id=agent.id, description="X")

	async def test_update_requires_id(self, tools):
		fns, as_, ks = tools
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_write"](mode="update", description="X"))
		assert "error" in result

	async def test_result_has_no_auto_learn(self, tools):
		fns, as_, ks = tools
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_write"](mode="create", name="ag", description="D", system_prompt="P"))
		assert "auto_learn" not in result

	async def test_anon_denied(self, tools):
		fns, as_, ks = tools
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="anonymous"), pytest.raises(PermissionError):
			await fns["agent_write"](mode="create", name="n", description="D", system_prompt="P")


# ── agent_delete ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAgentDelete:
	async def test_owner_can_delete_agent(self, tools):
		fns, as_, ks = tools
		agent = await as_.create(owner="alice", name="ag", description="D", system_prompt="P")
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="alice"):
			result = json.loads(await fns["agent_delete"](id=agent.id))
		assert result["deleted"] == agent.id
		assert await as_.get_by_id(agent.id) is None

	async def test_non_owner_denied(self, tools):
		fns, as_, ks = tools
		agent = await as_.create(owner="alice", name="ag", description="D", system_prompt="P")
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="bob"), pytest.raises(PermissionError):
			await fns["agent_delete"](id=agent.id)

	async def test_anon_denied(self, tools):
		fns, as_, ks = tools
		with patch("gabos_mcp.tools.agents.get_github_login", return_value="anonymous"), pytest.raises(PermissionError):
			await fns["agent_delete"](id="00000000-0000-0000-0000-000000000000")
