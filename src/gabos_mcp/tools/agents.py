"""MCP tools for managing and running domain-specific agents."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from platformdirs import user_cache_path

from gabos_mcp.extractors.agent_assembler import AgentAssembler
from gabos_mcp.extractors.chm import ChmExtractor
from gabos_mcp.utils.auth import get_github_login
from gabos_mcp.utils.stores import get_agent_store, get_knowledge_store

if TYPE_CHECKING:
	from fastmcp import FastMCP
	from fastmcp.server.context import Context


def register(mcp: FastMCP) -> None:
	"""Register agent tools on the given FastMCP instance."""
	agent_store = get_agent_store()
	knowledge_store = get_knowledge_store()

	chm_apps = json.loads(os.environ.get("GABOS_CHM_FILES", "{}"))
	chm_cache = os.environ.get("GABOS_CHM_CACHE_DIR", str(user_cache_path("gabos-mcp") / "chm"))
	chm_extractor = ChmExtractor(apps=chm_apps, cache_dir=chm_cache)

	assembler = AgentAssembler(
		agent_store=agent_store,
		knowledge_store=knowledge_store,
		chm_extractor=chm_extractor,
	)

	# ── Agent CRUD ──────────────────────────────────────────────────────────────

	@mcp.tool
	async def agent_create(
		name: str,
		description: str,
		system_prompt: str,
		model: str | None = None,
		knowledge_tags: list[str] | None = None,
		auto_learn: bool = True,
	) -> str:
		"""Create a new agent definition stored in the database.

		Args:
		    name: Unique slug identifier (e.g. "omnitracker").
		    description: One-line description shown in agent_list.
		    system_prompt: Full persona and response-format instructions for the agent.
		    model: Claude model ID hint stored for reference (default: claude-haiku-4-5-20251001).
		    knowledge_tags: Additional knowledge tags to auto-inject into context on each call.
		    auto_learn: Whether the agent supports learning extraction via agent_extract_learnings.
		"""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to create agents.")
		await agent_store.migrate()
		agent = await agent_store.create(
			owner=user,
			name=name,
			description=description,
			system_prompt=system_prompt,
			model=model,
			knowledge_tags=knowledge_tags,
			auto_learn=auto_learn,
		)
		return json.dumps(agent.to_dict(), indent=2)

	@mcp.tool
	async def agent_get(name_or_id: str) -> str:
		"""Get a single agent definition by name or ID."""
		await agent_store.migrate()
		agent = await agent_store.get(name_or_id)
		if agent is None:
			raise KeyError(f"Agent '{name_or_id}' not found.")
		return json.dumps(agent.to_dict(), indent=2)

	@mcp.tool
	async def agent_list() -> str:
		"""List all available agents with their name, owner, and description."""
		await agent_store.migrate()
		agents = await agent_store.list_agents()
		return json.dumps(
			[{"name": a.name, "owner": a.owner, "description": a.description} for a in agents],
			indent=2,
		)

	@mcp.tool
	async def agent_update(
		name_or_id: str,
		description: str | None = None,
		system_prompt: str | None = None,
		model: str | None = None,
		knowledge_tags: list[str] | None = None,
		auto_learn: bool | None = None,
	) -> str:
		"""Update an agent definition. Only the owner can edit their own agents."""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to update agents.")
		await agent_store.migrate()
		agent = await agent_store.update(
			name_or_id=name_or_id,
			owner=user,
			description=description,
			system_prompt=system_prompt,
			model=model,
			knowledge_tags=knowledge_tags,
			auto_learn=auto_learn,
		)
		return json.dumps(agent.to_dict(), indent=2)

	@mcp.tool
	async def agent_delete(name_or_id: str) -> str:
		"""Delete an agent and all its linked documentation references. Only the owner can delete."""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to delete agents.")
		await agent_store.migrate()
		await agent_store.delete(name_or_id, owner=user)
		return json.dumps({"deleted": name_or_id})

	# ── Agent Context ───────────────────────────────────────────────────────────

	@mcp.tool
	async def agent_context(
		agent: str,
		query: str,
		folder_context: str | None = None,
	) -> str:
		"""Assemble and return the context for a domain agent query.

		Returns the agent's system_prompt and a context_markdown block containing
		relevant knowledge entries and CHM documentation pages. Use system_prompt
		as your persona/instructions and context_markdown as the injected knowledge
		when answering the query.

		No external API calls are made — all data is read from the local database
		and CHM file cache.

		Args:
		    agent: Agent name or ID (see agent_list for available agents).
		    query: The question to be answered — used to rank knowledge hits via FTS.
		    folder_context: Optional folder/domain key (e.g. OmniTracker folder name)
		                    to inject folder-specific knowledge and doc refs.

		Returns:
		    JSON with system_prompt, context_markdown, and stats.
		"""
		await agent_store.migrate()
		await knowledge_store.migrate()
		result = await assembler.assemble(
			agent_name=agent,
			query=query,
			folder_context=folder_context,
		)
		return json.dumps(result.to_dict(), indent=2)

	# ── Learning ────────────────────────────────────────────────────────────────

	@mcp.tool
	async def agent_learn(
		agent: str,
		title: str,
		content: str,
		tags: list[str] | None = None,
	) -> str:
		"""Manually save a learning for an agent into the knowledge store.

		The tag agent:<name> is added automatically. Use this to directly record
		facts, field lists, API patterns, or anything the agent should know.

		Args:
		    agent: Agent name or ID.
		    title: Short descriptive title.
		    content: Markdown content.
		    tags: Additional tags (e.g. "agent:omnitracker:folder:Tickets").
		"""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to save agent learnings.")
		await agent_store.migrate()
		await knowledge_store.migrate()

		agent_obj = await agent_store.get(agent)
		if agent_obj is None:
			raise KeyError(f"Agent '{agent}' not found.")

		auto_tag = f"agent:{agent_obj.name}"
		all_tags = [auto_tag] + [t for t in (tags or []) if t != auto_tag]
		entry = await knowledge_store.add(owner=user, title=title, content=content, tags=all_tags)
		return json.dumps(entry, indent=2)

	@mcp.tool
	async def agent_extract_learnings(
		agent: str,
		query: str,
		answer: str,
		referenced_chm_pages: list[str] | None = None,
		folder_context: str | None = None,
		ctx: Context | None = None,
	) -> str:
		"""Extract and persist learnings from a completed Q&A interaction.

		Calls ctx.sample() to ask the active LLM session to extract reusable facts
		from the provided Q&A pair, then saves them to the knowledge store and doc refs.
		No external API key is required — uses the already-active client session.

		Call this after getting a good answer to preserve what was learned.

		Args:
		    agent: Agent name or ID.
		    query: The original question that was asked.
		    answer: The answer that was given (copy the agent_context response here).
		    referenced_chm_pages: CHM page paths referenced in the answer (app/source/path).
		    folder_context: The folder context that was used (if any).
		    ctx: FastMCP context (injected automatically — do not pass manually).
		"""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to save learnings.")
		await agent_store.migrate()
		await knowledge_store.migrate()

		summary = await assembler.extract_learnings(
			agent_name=agent,
			query=query,
			answer=answer,
			referenced_chm_pages=referenced_chm_pages or [],
			folder_context=folder_context,
			learn_owner=user,
			ctx=ctx,
		)
		return json.dumps(summary.to_dict(), indent=2)

	# ── Doc Ref Management ──────────────────────────────────────────────────────

	@mcp.tool
	async def agent_doc_ref_add(
		agent: str,
		context_key: str,
		app: str,
		source: str,
		page_path: str,
		relevance_note: str | None = None,
	) -> str:
		"""Manually link a CHM documentation page to an agent and context key.

		Args:
		    agent: Agent name or ID.
		    context_key: Folder or context name (e.g. "Tickets") or "_global".
		    app: CHM application name (e.g. "OMNITRACKER").
		    source: CHM source name within the app.
		    page_path: Page path within the source.
		    relevance_note: Why this page is relevant for this context.
		"""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to add doc refs.")
		await agent_store.migrate()
		ref = await agent_store.add_doc_ref(
			agent_name_or_id=agent,
			context_key=context_key,
			app=app,
			source=source,
			page_path=page_path,
			relevance_note=relevance_note,
			owner=user,
		)
		return json.dumps(ref.to_dict(), indent=2)

	@mcp.tool
	async def agent_doc_ref_list(
		agent: str,
		context_key: str | None = None,
	) -> str:
		"""List CHM documentation pages linked to an agent.

		Args:
		    agent: Agent name or ID.
		    context_key: Filter to a specific context key (e.g. "Tickets"). Omit for all.
		"""
		await agent_store.migrate()
		context_keys = [context_key] if context_key else None
		refs = await agent_store.list_doc_refs(agent, context_keys=context_keys)
		return json.dumps([r.to_dict() for r in refs], indent=2)

	@mcp.tool
	async def agent_doc_ref_delete(ref_id: str) -> str:
		"""Delete a documentation reference by its ID. Only the owning agent's owner can delete.

		Use agent_doc_ref_list to find the ID of the ref to delete.
		"""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to delete doc refs.")
		await agent_store.migrate()
		await agent_store.delete_doc_ref(ref_id, owner=user)
		return json.dumps({"deleted": ref_id})
