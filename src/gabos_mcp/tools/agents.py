"""MCP tools for managing and running domain-specific agents."""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Literal

from fastmcp.server.context import Context
from platformdirs import user_cache_path

from gabos_mcp.extractors.agent_assembler import AgentAssembler
from gabos_mcp.extractors.chm import ChmExtractor
from gabos_mcp.utils.auth import get_github_login
from gabos_mcp.utils.stores import get_agent_store, get_knowledge_store

if TYPE_CHECKING:
	from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:  # noqa: C901, PLR0915
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

	# ── Read ────────────────────────────────────────────────────────────────────

	@mcp.tool
	async def agent_read(
		name_or_id: str | None = None,
		include_doc_refs: bool = False,
		doc_ref_context_key: str | None = None,
	) -> str:
		"""Read agent definitions — fetch one agent or list all visible agents.

		Behaviour depends on which fields you provide:

		- name_or_id omitted → lists all agents visible to the current user
		  (own agents and shared agents), with name, owner, shared, and description.
		- name_or_id provided → returns full details for that agent.
		- name_or_id + include_doc_refs=true → includes the agent's doc refs in the
		  response. Optionally filter to a specific context key with doc_ref_context_key.

		Args:
		    name_or_id: Agent name or UUID. Omit to list all visible agents.
		    include_doc_refs: Include doc refs in the response (requires name_or_id).
		    doc_ref_context_key: Filter doc refs to this context key (e.g. "Tickets").
		"""
		user = get_github_login()
		caller = None if user == "anonymous" else user
		await agent_store.migrate()

		if name_or_id is None:
			agents = await agent_store.list_agents(caller=caller)
			return json.dumps(
				[{"name": a.name, "owner": a.owner, "shared": a.shared, "description": a.description} for a in agents],
				indent=2,
			)

		agent = await agent_store.get(name_or_id)
		if agent is None:
			raise KeyError(f"Agent '{name_or_id}' not found.")
		if caller is not None and agent.owner != caller and not agent.shared:
			raise PermissionError(f"Agent '{name_or_id}' not found or access denied.")

		result = agent.to_dict()
		if include_doc_refs:
			context_keys = [doc_ref_context_key] if doc_ref_context_key else None
			refs = await agent_store.list_doc_refs(name_or_id, context_keys=context_keys)
			result["doc_refs"] = [r.to_dict() for r in refs]

		return json.dumps(result, indent=2)

	# ── Context ─────────────────────────────────────────────────────────────────

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
		    agent: Agent name or ID (see agent_read for available agents).
		    query: The question to be answered — used to rank knowledge hits via FTS.
		    folder_context: Optional folder/domain key (e.g. OmniTracker folder name)
		                    to inject folder-specific knowledge and doc refs.

		Returns:
		    JSON with system_prompt, context_markdown, and stats.
		"""
		user = get_github_login()
		await agent_store.migrate()
		await knowledge_store.migrate()
		agent_obj = await agent_store.get(agent)
		if agent_obj is None:
			raise KeyError(f"Agent '{agent}' not found.")
		caller = None if user == "anonymous" else user
		if caller is not None and agent_obj.owner != caller and not agent_obj.shared:
			raise PermissionError(f"Agent '{agent}' not found or access denied.")
		result = await assembler.assemble(
			agent_name=agent,
			query=query,
			folder_context=folder_context,
			caller=caller,
		)
		return json.dumps(result.to_dict(), indent=2)

	# ── Learning extraction ──────────────────────────────────────────────────────

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

		Only the agent owner may extract learnings.

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

		agent_obj = await agent_store.get(agent)
		if agent_obj is None:
			raise KeyError(f"Agent '{agent}' not found.")
		if agent_obj.owner != user:
			raise PermissionError("Only the agent owner can extract learnings.")

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

	# ── Write ────────────────────────────────────────────────────────────────────

	@mcp.tool
	async def agent_write(  # noqa: C901, PLR0912
		mode: Literal["create", "update"],
		name_or_id: str | None = None,
		name: str | None = None,
		description: str | None = None,
		system_prompt: str | None = None,
		model: str | None = None,
		knowledge_tags: list[str] | None = None,
		auto_learn: bool | None = None,
		shared: bool | None = None,
		doc_refs: list[dict] | None = None,
		learnings: list[dict] | None = None,
	) -> str:
		"""Create or update an agent definition. Authentication required. Owner-only writes.

		Use mode="create" to define a new agent, mode="update" to modify an existing one.

		mode="create":
		  - name, description, and system_prompt are required.
		  - name_or_id must be omitted.
		  - model defaults to claude-haiku-4-5-20251001.
		  - shared defaults to false (private to you).

		mode="update":
		  - name_or_id is required (agent name or UUID).
		  - All other fields are partial overrides — omit any field to keep its current value.
		  - Only the agent owner may update.

		Both modes accept these optional fields:

		doc_refs: list of CHM page links to add. Each entry must have:
		  {context_key, app, source, page_path, relevance_note?}
		  On update, entries are added if not already present; existing refs are not removed.
		  To remove refs, use agent_delete with doc_ref_ids.

		learnings: list of knowledge entries to write to the knowledge store, tagged
		  automatically with agent:<name>. Each entry must have {title, content} and
		  optionally {tags, shared}. The agent:<name> tag is prepended automatically.
		  NOTE: learnings are stored in the shared knowledge store, not inside the agent
		  record. Deleting the agent later does NOT delete these entries. Remove them
		  explicitly with knowledge_delete if no longer needed.

		Args:
		    mode: "create" to add a new agent, "update" to modify an existing one.
		    name_or_id: Agent name or UUID. Required for update; omit for create.
		    name: Agent slug (e.g. "omnitracker"). Required for create.
		    description: One-line description. Required for create.
		    system_prompt: Full persona and instructions. Required for create.
		    model: Claude model ID hint (default: claude-haiku-4-5-20251001).
		    knowledge_tags: Extra knowledge tags to inject into context.
		    auto_learn: Whether agent_extract_learnings is supported (default: true).
		    shared: Whether agent is visible to all authenticated users (default: false).
		    doc_refs: CHM page links to attach (see above).
		    learnings: Knowledge entries to persist tagged to this agent (see above).
		"""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to write agents.")
		await agent_store.migrate()
		await knowledge_store.migrate()

		if mode == "create":
			if name_or_id is not None:
				return json.dumps({"error": "name_or_id must be omitted for mode='create'. Use name instead."})
			if not name:
				return json.dumps({"error": "name is required for mode='create'."})
			if not description:
				return json.dumps({"error": "description is required for mode='create'."})
			if not system_prompt:
				return json.dumps({"error": "system_prompt is required for mode='create'."})

			agent = await agent_store.create(
				owner=user,
				name=name,
				description=description,
				system_prompt=system_prompt,
				model=model,
				knowledge_tags=knowledge_tags,
				auto_learn=auto_learn if auto_learn is not None else True,
				shared=shared if shared is not None else False,
			)

		elif mode == "update":
			if not name_or_id:
				return json.dumps({"error": "name_or_id is required for mode='update'."})
			agent = await agent_store.update(
				name_or_id=name_or_id,
				owner=user,
				description=description,
				system_prompt=system_prompt,
				model=model,
				knowledge_tags=knowledge_tags,
				auto_learn=auto_learn,
				shared=shared,
			)

		else:
			return json.dumps({"error": f"Unknown mode '{mode}'. Use 'create' or 'update'."})

		# Add doc refs (additive — duplicates are silently skipped)
		refs_added: list[str] = []
		refs_skipped: list[str] = []
		for ref in doc_refs or []:
			try:
				await agent_store.add_doc_ref(
					agent_name_or_id=agent.name,
					context_key=ref.get("context_key", "_global"),
					app=ref["app"],
					source=ref["source"],
					page_path=ref["page_path"],
					relevance_note=ref.get("relevance_note"),
					caller=user,
				)
				refs_added.append(f"{ref.get('app')}/{ref.get('source')}/{ref.get('page_path')}")
			except ValueError:
				refs_skipped.append(f"{ref.get('app')}/{ref.get('source')}/{ref.get('page_path')}")

		# Save learnings to the knowledge store tagged with agent:<name>
		learnings_saved: list[str] = []
		auto_tag = f"agent:{agent.name}"
		for item in learnings or []:
			extra_tags = [t for t in (item.get("tags") or []) if t != auto_tag]
			all_tags = [auto_tag, *extra_tags]
			try:
				await knowledge_store.add(
					owner=user,
					title=item["title"],
					content=item["content"],
					tags=all_tags,
					shared=item.get("shared", False),
				)
				learnings_saved.append(item["title"])
			except Exception:  # noqa: BLE001
				logger.warning("Failed to save learning: %s", item.get("title"))

		result = agent.to_dict()
		if refs_added or refs_skipped:
			result["doc_refs_added"] = refs_added
			result["doc_refs_skipped_duplicates"] = refs_skipped
		if learnings_saved:
			result["learnings_saved"] = learnings_saved

		return json.dumps(result, indent=2)

	# ── Delete ───────────────────────────────────────────────────────────────────

	@mcp.tool
	async def agent_delete(name_or_id: str, doc_ref_ids: list[str] | None = None) -> str:
		"""Delete an agent or remove specific doc refs from an agent. Owner-only.

		Behaviour depends on whether doc_ref_ids is provided:

		- doc_ref_ids omitted → deletes the agent and all its doc refs entirely.
		- doc_ref_ids provided → deletes only those specific doc refs and leaves the
		  agent intact. Use agent_read with include_doc_refs=true to find ref IDs.

		IMPORTANT: Knowledge entries tagged to the agent (agent:<name>) are stored
		independently and are NOT deleted when the agent is deleted. Remove them
		explicitly with knowledge_delete if they are no longer needed.

		Args:
		    name_or_id: Agent name or UUID.
		    doc_ref_ids: If provided, delete only these doc refs (not the agent itself).
		"""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to delete agents.")
		await agent_store.migrate()

		if doc_ref_ids is not None:
			deleted: list[str] = []
			errors: list[str] = []
			for ref_id in doc_ref_ids:
				try:
					await agent_store.delete_doc_ref(ref_id, caller=user)
					deleted.append(ref_id)
				except (KeyError, PermissionError) as exc:
					errors.append(f"{ref_id}: {exc}")
			result: dict = {"deleted_doc_refs": deleted}
			if errors:
				result["errors"] = errors
			return json.dumps(result, indent=2)

		await agent_store.delete(name_or_id, owner=user)
		return json.dumps({"deleted": name_or_id})
