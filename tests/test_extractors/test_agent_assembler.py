import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from gabos_mcp.extractors.agent_assembler import AgentAssembler, AssembledContext, LearningSummary
from gabos_mcp.extractors.agent_store import AgentStore
from gabos_mcp.extractors.knowledge import KnowledgeStore


@pytest_asyncio.fixture
async def agent_store(tmp_path):
	s = AgentStore(db_path=str(tmp_path / "agents.db"))
	await s.migrate()
	return s


@pytest_asyncio.fixture
async def knowledge_store(tmp_path):
	s = KnowledgeStore(db_path=str(tmp_path / "knowledge.db"))
	await s.migrate()
	return s


@pytest_asyncio.fixture
async def agent(agent_store):
	return await agent_store.create(
		owner="alice",
		name="test-agent",
		description="Test domain expert",
		system_prompt="You are a test expert.",
		knowledge_tags=["test"],
	)


def _make_ctx(sample_response: str) -> MagicMock:
	ctx = MagicMock()
	ctx.sample = AsyncMock(return_value=sample_response)
	return ctx


@pytest.mark.asyncio
class TestAssemble:
	async def test_raises_for_unknown_agent(self, agent_store, knowledge_store):
		assembler = AgentAssembler(agent_store=agent_store, knowledge_store=knowledge_store)
		with pytest.raises(KeyError, match="not found"):
			await assembler.assemble("ghost", "query")

	async def test_returns_assembled_context(self, agent_store, knowledge_store, agent):
		assembler = AgentAssembler(agent_store=agent_store, knowledge_store=knowledge_store)
		result = await assembler.assemble("test-agent", "anything")
		assert isinstance(result, AssembledContext)
		assert result.system_prompt == "You are a test expert."

	async def test_injects_global_agent_knowledge(self, agent_store, knowledge_store, agent):
		await knowledge_store.add(
			owner="alice", title="Important fact", content="fact content", tags=["agent:test-agent"]
		)
		assembler = AgentAssembler(agent_store=agent_store, knowledge_store=knowledge_store)
		result = await assembler.assemble("test-agent", "important fact query")
		assert "Important fact" in result.context_markdown
		assert result.knowledge_count == 1

	async def test_injects_folder_specific_knowledge(self, agent_store, knowledge_store, agent):
		await knowledge_store.add(
			owner="alice",
			title="Folder field",
			content="field content",
			tags=["agent:test-agent:folder:Tickets"],
		)
		assembler = AgentAssembler(agent_store=agent_store, knowledge_store=knowledge_store)
		result = await assembler.assemble("test-agent", "anything", folder_context="Tickets")
		assert "Folder field" in result.context_markdown

	async def test_empty_context_when_no_knowledge(self, agent_store, knowledge_store, agent):
		assembler = AgentAssembler(agent_store=agent_store, knowledge_store=knowledge_store)
		result = await assembler.assemble("test-agent", "query")
		assert result.knowledge_count == 0
		assert result.doc_page_count == 0

	async def test_deduplicates_knowledge_entries(self, agent_store, knowledge_store, agent):
		# Add entry with both agent tag AND extra knowledge_tag
		await knowledge_store.add(
			owner="alice", title="Shared fact", content="content", tags=["agent:test-agent", "test"]
		)
		assembler = AgentAssembler(agent_store=agent_store, knowledge_store=knowledge_store)
		result = await assembler.assemble("test-agent", "shared fact query")
		# Should appear exactly once despite matching two tags
		assert result.context_markdown.count("Shared fact") == 1


@pytest.mark.asyncio
class TestExtractLearnings:
	async def test_raises_without_ctx(self, agent_store, knowledge_store, agent):
		assembler = AgentAssembler(agent_store=agent_store, knowledge_store=knowledge_store)
		with pytest.raises(ValueError, match="ctx is required"):
			await assembler.extract_learnings("test-agent", "q", "a", [], ctx=None)

	async def test_raises_for_unknown_agent(self, agent_store, knowledge_store):
		assembler = AgentAssembler(agent_store=agent_store, knowledge_store=knowledge_store)
		ctx = _make_ctx(json.dumps({"knowledge": [], "doc_refs": []}))
		with pytest.raises(KeyError, match="not found"):
			await assembler.extract_learnings("ghost", "q", "a", [], ctx=ctx)

	async def test_saves_knowledge_entries(self, agent_store, knowledge_store, agent):
		learnings = json.dumps(
			{
				"knowledge": [{"title": "New fact", "content": "content", "tags": ["agent:test-agent"]}],
				"doc_refs": [],
			}
		)
		assembler = AgentAssembler(agent_store=agent_store, knowledge_store=knowledge_store)
		summary = await assembler.extract_learnings(
			"test-agent", "query", "answer", [], ctx=_make_ctx(learnings), learn_owner="alice"
		)
		assert isinstance(summary, LearningSummary)
		assert summary.knowledge_saved == 1
		entries = await knowledge_store.list_entries(tag="agent:test-agent")
		assert len(entries) == 1

	async def test_saves_doc_refs_for_referenced_pages(self, agent_store, knowledge_store, agent):
		learnings = json.dumps(
			{
				"knowledge": [],
				"doc_refs": [{"context_key": "_global", "app": "APP", "source": "src", "page_path": "pg"}],
			}
		)
		assembler = AgentAssembler(agent_store=agent_store, knowledge_store=knowledge_store)
		summary = await assembler.extract_learnings(
			"test-agent",
			"query",
			"answer",
			referenced_chm_pages=["APP/src/pg"],
			ctx=_make_ctx(learnings),
		)
		assert summary.doc_refs_saved == 1

	async def test_skips_doc_refs_not_in_referenced_pages(self, agent_store, knowledge_store, agent):
		learnings = json.dumps(
			{
				"knowledge": [],
				"doc_refs": [{"context_key": "_global", "app": "APP", "source": "src", "page_path": "pg"}],
			}
		)
		assembler = AgentAssembler(agent_store=agent_store, knowledge_store=knowledge_store)
		# Pass a different referenced page — should not save the doc ref
		summary = await assembler.extract_learnings(
			"test-agent",
			"query",
			"answer",
			referenced_chm_pages=["OTHER/src/other-page"],
			ctx=_make_ctx(learnings),
		)
		assert summary.doc_refs_saved == 0

	async def test_duplicate_doc_ref_silently_skipped(self, agent_store, knowledge_store, agent):
		await agent_store.add_doc_ref("test-agent", "_global", "APP", "src", "pg")
		learnings = json.dumps(
			{
				"knowledge": [],
				"doc_refs": [{"context_key": "_global", "app": "APP", "source": "src", "page_path": "pg"}],
			}
		)
		assembler = AgentAssembler(agent_store=agent_store, knowledge_store=knowledge_store)
		summary = await assembler.extract_learnings("test-agent", "q", "a", ["APP/src/pg"], ctx=_make_ctx(learnings))
		assert summary.doc_refs_saved == 0

	async def test_returns_zero_on_malformed_ctx_response(self, agent_store, knowledge_store, agent):
		ctx = _make_ctx("not valid json at all")
		assembler = AgentAssembler(agent_store=agent_store, knowledge_store=knowledge_store)
		summary = await assembler.extract_learnings("test-agent", "q", "a", [], ctx=ctx)
		assert summary.knowledge_saved == 0
		assert summary.doc_refs_saved == 0

	async def test_strips_markdown_fences_from_ctx_response(self, agent_store, knowledge_store, agent):
		fenced = '```json\n{"knowledge": [], "doc_refs": []}\n```'
		assembler = AgentAssembler(agent_store=agent_store, knowledge_store=knowledge_store)
		summary = await assembler.extract_learnings("test-agent", "q", "a", [], ctx=_make_ctx(fenced))
		assert summary.knowledge_saved == 0
