"""MCP tools for managing domain-specific agents."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Literal

from gabos_mcp.utils.auth import get_github_login
from gabos_mcp.utils.stores import get_agent_store

if TYPE_CHECKING:
	from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:  # noqa: C901
	"""Register agent tools on the given FastMCP instance."""
	agent_store = get_agent_store()

	# ── Read ────────────────────────────────────────────────────────────────────

	@mcp.tool
	async def agent_search(
		query: str | None = None,
	) -> str:
		"""List agents visible to the current user, optionally filtered by a query.

		Returns id, name, owner, shared, and description for each matching agent.
		Use agent_read(id=...) to fetch full details including system_prompt.

		Args:
		    query: Optional filter — case-insensitive substring match against name
		      and description. Omit to list all visible agents.
		"""
		user = get_github_login()
		caller = None if user == "anonymous" else user
		await agent_store.migrate()

		agents = await agent_store.list_agents(caller=caller)
		if query:
			q = query.lower()
			agents = [a for a in agents if q in a.name.lower() or q in (a.description or "").lower()]
		return json.dumps(
			[
				{"id": a.id, "name": a.name, "owner": a.owner, "shared": a.shared, "description": a.description}
				for a in agents
			],
			indent=2,
		)

	@mcp.tool
	async def agent_read(
		id: str,
	) -> str:
		"""Fetch full details for a single agent by UUID, including system_prompt and knowledge_tags.

		Use agent_search to discover agent IDs.

		**Agent Q&A flow**:
		1. agent_search() → pick agent, note id and name
		2. agent_read(id=...) → system_prompt, knowledge_tags
		3. knowledge_search(query, tag="agent:<name>"). If knowledge_tags is
		   non-empty, run one additional knowledge_search per listed tag and merge.
		4. knowledge_read(id=...) for entries worth reading
		5. docs_search / docs_read if CHM documentation is relevant
		6. Answer using system_prompt as persona
		7. knowledge_write(tags=["agent:<name>"]) to persist new facts

		Args:
		    id: Agent UUID.
		"""
		user = get_github_login()
		caller = None if user == "anonymous" else user
		await agent_store.migrate()

		agent = await agent_store.get_by_id(id, caller=caller)
		if agent is None:
			raise KeyError(f"Agent '{id}' not found.")
		return json.dumps(agent.to_dict(), indent=2)

	# ── Write ────────────────────────────────────────────────────────────────────

	@mcp.tool
	async def agent_write(
		mode: Literal["create", "update"],
		id: str | None = None,
		name: str | None = None,
		description: str | None = None,
		system_prompt: str | None = None,
		knowledge_tags: list[str] | None = None,
		shared: bool | None = None,
	) -> str:
		"""Create or update an agent definition. Authentication required. Owner-only writes.

		Use mode="create" to define a new agent, mode="update" to modify an existing one.

		mode="create": name, description, and system_prompt are required; id must
		  be omitted; shared defaults to false.

		mode="update": id is required; description, system_prompt, knowledge_tags,
		  and shared are partial overrides (omit to keep current value); only the
		  agent owner may update. Passing name returns an error — agent names are
		  immutable.

		To attach knowledge to an agent, use knowledge_write with tags=["agent:<name>"].

		Args:
		    mode: "create" to add a new agent, "update" to modify an existing one.
		    id: Agent UUID. Required for update; omit for create.
		    name: Agent slug (e.g. "omnitracker"). Required for create; immutable after creation.
		    description: One-line description. Required for create.
		    system_prompt: Full persona and instructions. Required for create.
		    knowledge_tags: Optional extra tag scopes the agent searches in addition
		      to its own agent:<name> namespace (e.g. a shared agent:common). Leave
		      empty to search only agent:<name>.
		    shared: Whether agent is visible to all authenticated users (default: false).
		"""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to write agents.")
		await agent_store.migrate()

		if mode == "create":
			if id is not None:
				return json.dumps({"error": "id must be omitted for mode='create'."})
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
				knowledge_tags=knowledge_tags,
				shared=shared if shared is not None else False,
			)

		elif mode == "update":
			if not id:
				return json.dumps({"error": "id is required for mode='update'."})
			if name is not None:
				return json.dumps({"error": "name is immutable and cannot be changed after creation."})
			agent = await agent_store.update(
				id=id,
				owner=user,
				description=description,
				system_prompt=system_prompt,
				knowledge_tags=knowledge_tags,
				shared=shared,
			)

		else:
			return json.dumps({"error": f"Unknown mode '{mode}'. Use 'create' or 'update'."})

		return json.dumps(agent.to_dict(), indent=2)

	# ── Delete ───────────────────────────────────────────────────────────────────

	@mcp.tool
	async def agent_delete(id: str) -> str:
		"""Delete an agent. Owner-only.

		Deletes the agent definition entirely. Knowledge entries tagged to the
		agent (agent:<name>) are stored independently and are NOT deleted when
		the agent is deleted. Remove them explicitly with knowledge_delete if
		they are no longer needed.

		Args:
		    id: Agent UUID.
		"""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to delete agents.")
		await agent_store.migrate()

		await agent_store.delete(id, owner=user)
		return json.dumps({"deleted": id})
