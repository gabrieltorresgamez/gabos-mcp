"""MCP tools and resources for the shared knowledge store."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Literal

from gabos_mcp.utils.auth import get_github_login
from gabos_mcp.utils.stores import get_agent_store, get_knowledge_store

if TYPE_CHECKING:
	from fastmcp import FastMCP

	from gabos_mcp.extractors.agent_store import AgentStore

_AGENT_TAG_RE = re.compile(r"^agent:([^:]+)")


async def _assert_agent_tags_owned(caller: str, tags: list[str], agent_store: AgentStore) -> None:
	"""Raise PermissionError if caller uses agent: tags without owning those agents.

	Resolves all referenced agent names in a single query for efficiency.
	"""
	agent_names: set[str] = set()
	for tag in tags:
		m = _AGENT_TAG_RE.match(tag)
		if m:
			agent_names.add(m.group(1))
	if not agent_names:
		return
	await agent_store.migrate()
	agents_by_name = await agent_store.get_many(list(agent_names))
	for name in agent_names:
		agent = agents_by_name.get(name)
		if agent is None or agent.owner != caller:
			raise PermissionError(
				f"Tag 'agent:{name}' requires you to own agent '{name}'. "
				"Only the agent owner may tag knowledge with their agent's name."
			)


def register(mcp: FastMCP) -> None:  # noqa: C901
	"""Register knowledge tools and resources on the given FastMCP instance."""
	store = get_knowledge_store()
	agent_store = get_agent_store()

	@mcp.tool
	async def knowledge_read(
		id: str | None = None,
		owner: str | None = None,
		tag: str | None = None,
		limit: int = 50,
		offset: int = 0,
	) -> str:
		"""Read knowledge entries — fetch a single entry by ID or list entries.

		Behaviour depends on which fields you provide:

		- id provided → returns that single entry (full content). Requires visibility
		  (own entry or shared=true).
		- id omitted → lists entries visible to the current user (own entries and shared
		  entries from others), optionally filtered by owner and/or tag, paginated via
		  limit/offset.

		Args:
		    id: Entry ID. Provide to fetch a specific entry; omit to list.
		    owner: Filter list results to entries from this owner (list mode only).
		    tag: Filter list results to entries containing this tag (list mode only).
		    limit: Max entries to return when listing.
		    offset: Entries to skip when listing.
		"""
		user = get_github_login()
		caller = None if user == "anonymous" else user
		await store.migrate()

		if id is not None:
			entry = await store.get(id)
			if entry is None:
				raise KeyError(f"Knowledge entry '{id}' not found.")
			if caller is not None and entry["owner"] != caller and not entry.get("shared"):
				raise PermissionError(f"Knowledge entry '{id}' not found or access denied.")
			return json.dumps(entry, indent=2)

		entries = await store.list_entries(owner=owner, tag=tag, limit=limit, offset=offset, caller=caller)
		return json.dumps(entries, indent=2)

	@mcp.tool
	async def knowledge_write(
		mode: Literal["create", "update"],
		id: str | None = None,
		title: str | None = None,
		content: str | None = None,
		tags: list[str] | None = None,
		shared: bool = False,
	) -> str:
		"""Create or update a knowledge entry. Authentication required.

		Use mode="create" to add a new entry, mode="update" to modify an existing one.

		mode="create":
		  - title and content are required; id must be omitted.
		  - Creates the entry owned by the current user.

		mode="update":
		  - id is required; other fields are partial overrides (omit to keep existing value).
		  - Only the entry's owner may update.

		Both modes: if any tag matches agent:<name> or agent:<name>:folder:<key>, you must
		own that agent. Only the agent owner may tag knowledge with their agent's name.

		Args:
		    mode: "create" to add a new entry, "update" to modify an existing one.
		    id: Entry ID. Required for update; must be omitted for create.
		    title: Entry title. Required for create.
		    content: Markdown content. Required for create.
		    tags: Tag list. Optional for create; partial override for update.
		    shared: Whether visible to all authenticated users (default: false).
		"""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to write knowledge.")
		await store.migrate()

		if mode == "create":
			if id is not None:
				return json.dumps({"error": "id must be omitted for mode='create'."})
			if not title:
				return json.dumps({"error": "title is required for mode='create'."})
			if content is None:
				return json.dumps({"error": "content is required for mode='create'."})
			if tags:
				await _assert_agent_tags_owned(user, tags, agent_store)
			entry = await store.add(owner=user, title=title, content=content, tags=tags, shared=shared)
			return json.dumps(entry, indent=2)

		if mode == "update":
			if not id:
				return json.dumps({"error": "id is required for mode='update'."})
			if tags is not None:
				await _assert_agent_tags_owned(user, tags, agent_store)
			entry = await store.update(
				id=id,
				owner=user,
				title=title,
				content=content,
				tags=tags,
				shared=shared if shared is not None else None,
			)
			return json.dumps(entry, indent=2)

		return json.dumps({"error": f"Unknown mode '{mode}'. Use 'create' or 'update'."})

	@mcp.tool
	async def knowledge_delete(id: str) -> str:
		"""Delete a knowledge entry. Only the entry's owner may delete.

		Note: knowledge entries tagged to an agent (agent:<name>) are stored
		independently of the agent. Deleting the agent does NOT delete them.
		Remove them explicitly here when no longer needed.
		"""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to delete knowledge.")
		await store.migrate()
		await store.delete(id=id, owner=user)
		return json.dumps({"deleted": id})

