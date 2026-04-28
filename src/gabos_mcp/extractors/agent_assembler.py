"""AgentAssembler: assembles context from knowledge + CHM docs, and extracts learnings."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from fastmcp.server.context import Context

	from gabos_mcp.extractors.agent_store import Agent, AgentStore
	from gabos_mcp.extractors.chm import ChmExtractor
	from gabos_mcp.extractors.knowledge import KnowledgeStore

logger = logging.getLogger(__name__)

_LEARNING_EXTRACTION_TMPL = """\
You are a memory consolidation system. Analyze this agent interaction and extract \
what should be permanently remembered for future use.

AGENT: {agent_name} — {agent_description}
QUERY: {query}
FOLDER CONTEXT: {folder_context}
ANSWER: {answer}

Extract and return ONLY valid JSON in this exact structure:
{{
  "knowledge": [
    {{
      "title": "...",
      "content": "...",
      "tags": ["agent:{agent_name}"]
    }}
  ],
  "doc_refs": [
    {{
      "context_key": "...",
      "app": "...",
      "source": "...",
      "page_path": "...",
      "relevance_note": "..."
    }}
  ]
}}

Rules:
- knowledge: only genuinely reusable facts (field names, API patterns, error causes, \
business rules). Skip obvious or query-specific answers.
- For folder-specific facts, use tag "agent:{agent_name}:folder:<folder_name>".
- doc_refs: only add if a specific CHM page path was referenced in the answer \
(from referenced_chm_pages). context_key should be the folder name or "_global".
- Return {{"knowledge": [], "doc_refs": []}} if nothing is worth persisting.
"""


@dataclass
class AssembledContext:
	"""Result of context assembly for an agent query."""

	system_prompt: str
	context_markdown: str
	knowledge_count: int
	doc_page_count: int

	def to_dict(self) -> dict:
		"""Serialize to plain dict for JSON output.

		Returns:
		    Plain dict representation of this assembled context.
		"""
		return {
			"system_prompt": self.system_prompt,
			"context_markdown": self.context_markdown,
			"stats": {
				"knowledge_entries": self.knowledge_count,
				"doc_pages": self.doc_page_count,
			},
		}


@dataclass
class LearningSummary:
	"""Result of a learning extraction pass."""

	knowledge_saved: int
	doc_refs_saved: int

	def to_dict(self) -> dict:
		"""Serialize to plain dict for JSON output.

		Returns:
		    Plain dict representation of this learning summary.
		"""
		return {
			"knowledge_saved": self.knowledge_saved,
			"doc_refs_saved": self.doc_refs_saved,
		}


class AgentAssembler:
	"""Assembles context for agents and persists learnings via ctx.sample().

	No external API calls — context assembly reads only from SQLite and the
	CHM file cache. Learning extraction calls ctx.sample() which uses the
	already-active client LLM session (no separate API key required).
	"""

	def __init__(
		self,
		agent_store: AgentStore,
		knowledge_store: KnowledgeStore,
		chm_extractor: ChmExtractor | None = None,
	) -> None:
		"""Initialize.

		Args:
		    agent_store: Store for agent definitions and doc refs.
		    knowledge_store: Store for knowledge entries.
		    chm_extractor: Optional CHM extractor for reading doc page content.
		"""
		self._agents = agent_store
		self._knowledge = knowledge_store
		self._chm = chm_extractor

	async def _gather_knowledge_entries(
		self,
		agent: Agent,
		query: str,
		folder_context: str | None,
		caller: str | None,
	) -> list[dict]:
		tags = [f"agent:{agent.name}", *agent.knowledge_tags]

		fts_results: list[dict] = []
		for tag in tags:
			for hit in await self._knowledge.search(query, tag=tag, limit=10, caller=caller):
				if not any(h["id"] == hit["id"] for h in fts_results):
					fts_results.append(hit)
		fts_results = fts_results[:10]

		baseline: list[dict] = []
		for tag in tags:
			for entry in await self._knowledge.list_entries(tag=tag, limit=30, caller=caller, include_content=True):
				if not any(e["id"] == entry["id"] for e in baseline):
					baseline.append(entry)

		folder_results: list[dict] = []
		if folder_context:
			folder_tag = f"agent:{agent.name}:folder:{folder_context}"
			folder_results = await self._knowledge.list_entries(
				tag=folder_tag, limit=20, caller=caller, include_content=True
			)

		seen: set[str] = set()
		merged: list[dict] = []
		for entry in fts_results + baseline + folder_results:
			if entry["id"] not in seen:
				seen.add(entry["id"])
				merged.append(entry)
		return merged

	async def _gather_doc_pages(self, agent_name: str, folder_context: str | None) -> tuple[list[str], int]:
		context_keys = ["_global"]
		if folder_context:
			context_keys.append(folder_context)

		doc_refs = await self._agents.list_doc_refs(agent_name, context_keys=context_keys)
		if not doc_refs or self._chm is None:
			return [], 0

		sections: list[str] = []
		for ref in doc_refs:
			try:
				page_content = await self._chm.read_page(ref.app, ref.source, ref.page_path)
				note = f" — {ref.relevance_note}" if ref.relevance_note else ""
				sections.append(f"### {ref.app}/{ref.source}/{ref.page_path}{note}\n\n{page_content}\n")
			except Exception:  # noqa: BLE001
				logger.warning("Failed to read CHM page %s/%s/%s", ref.app, ref.source, ref.page_path)
		return sections, len(sections)

	async def assemble(
		self,
		agent_name: str,
		query: str,
		folder_context: str | None = None,
		caller: str | None = None,
	) -> AssembledContext:
		"""Assemble the context a Claude session needs to answer a query as the agent.

		Retrieves:
		1. FTS-ranked knowledge entries matching the query (global agent tags).
		2. All folder-specific knowledge entries (when folder_context is given).
		3. Content of CHM pages linked via agent_doc_refs for this context.

		Args:
		    agent_name: Agent name or ID.
		    query: The user's question — used to rank FTS knowledge hits.
		    folder_context: Optional folder/domain context key (e.g. "Tickets").
		    caller: GitHub login of the calling user, used to filter knowledge
		            to entries visible to them (own + shared).

		Returns:
		    AssembledContext with system_prompt, context_markdown, and stats.

		Raises:
		    KeyError: If the agent does not exist.
		"""
		agent = await self._agents.get(agent_name)
		if agent is None:
			raise KeyError(f"Agent '{agent_name}' not found.")

		sections: list[str] = []

		all_knowledge = await self._gather_knowledge_entries(agent, query, folder_context, caller)
		if all_knowledge:
			sections.append("## Knowledge Base\n")
			for entry in all_knowledge:
				tags_str = ", ".join(entry.get("tags", []))
				sections.append(f"### {entry['title']}\n*tags: {tags_str}*\n\n{entry['content']}\n")

		doc_sections, doc_page_count = await self._gather_doc_pages(agent.name, folder_context)
		if doc_sections:
			sections.append("## Documentation Pages\n")
			sections.extend(doc_sections)

		if folder_context:
			sections.append(f"## Current Folder Context\n\n`{folder_context}`\n")

		return AssembledContext(
			system_prompt=agent.system_prompt,
			context_markdown="\n".join(sections),
			knowledge_count=len(all_knowledge),
			doc_page_count=doc_page_count,
		)

	async def _persist_knowledge(self, items: list[dict], agent_name: str, learn_owner: str) -> int:
		saved = 0
		for item in items:
			try:
				await self._knowledge.add(
					owner=learn_owner,
					title=item["title"],
					content=item["content"],
					tags=item.get("tags", [f"agent:{agent_name}"]),
				)
				saved += 1
			except Exception:  # noqa: BLE001
				logger.warning("Failed to persist knowledge item: %s", item.get("title"))
		return saved

	async def _persist_doc_refs(self, items: list[dict], agent_name: str, referenced_chm_pages: list[str]) -> int:
		saved = 0
		for item in items:
			page_key = f"{item.get('app', '')}/{item.get('source', '')}/{item.get('page_path', '')}"
			if referenced_chm_pages and not any(page_key in ref or ref in page_key for ref in referenced_chm_pages):
				continue
			try:
				await self._agents.add_doc_ref(
					agent_name_or_id=agent_name,
					context_key=item.get("context_key", "_global"),
					app=item["app"],
					source=item["source"],
					page_path=item["page_path"],
					relevance_note=item.get("relevance_note"),
				)
				saved += 1
			except ValueError:
				pass  # already exists — silently skip
			except Exception:  # noqa: BLE001
				logger.warning("Failed to persist doc ref: %s", item)
		return saved

	async def extract_learnings(
		self,
		agent_name: str,
		query: str,
		answer: str,
		referenced_chm_pages: list[str],
		folder_context: str | None = None,
		learn_owner: str = "agent",
		ctx: Context | None = None,
	) -> LearningSummary:
		"""Extract and persist learnings from a completed Q&A using ctx.sample().

		Args:
		    agent_name: Agent name or ID.
		    query: The original query that was asked.
		    answer: The answer that was given (used to extract learnings from).
		    referenced_chm_pages: CHM page paths the answer referenced (format: app/source/path).
		    folder_context: Optional folder context used in the query.
		    learn_owner: Owner name for persisted knowledge entries.
		    ctx: FastMCP Context object. Required — raises ValueError if None.

		Returns:
		    LearningSummary with counts of what was saved.

		Raises:
		    KeyError: If the agent does not exist.
		    ValueError: If ctx is None.
		"""
		if ctx is None:
			raise ValueError("ctx is required for learning extraction.")

		agent = await self._agents.get(agent_name)
		if agent is None:
			raise KeyError(f"Agent '{agent_name}' not found.")

		prompt = _LEARNING_EXTRACTION_TMPL.format(
			agent_name=agent.name,
			agent_description=agent.description,
			query=query,
			folder_context=folder_context or "none",
			answer=answer,
		)

		try:
			raw = await ctx.sample(prompt)
			raw_text = raw if isinstance(raw, str) else getattr(raw, "text", str(raw))
			text = raw_text.strip()
			if text.startswith("```"):
				lines = text.splitlines()
				text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
			learnings = json.loads(text)
		except Exception:  # noqa: BLE001
			logger.warning("Learning extraction failed — skipping persistence.")
			return LearningSummary(knowledge_saved=0, doc_refs_saved=0)

		knowledge_saved = await self._persist_knowledge(learnings.get("knowledge", []), agent.name, learn_owner)
		doc_refs_saved = await self._persist_doc_refs(learnings.get("doc_refs", []), agent.name, referenced_chm_pages)
		return LearningSummary(knowledge_saved=knowledge_saved, doc_refs_saved=doc_refs_saved)
