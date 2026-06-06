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
	async def agent_read(
		name_or_id: str | None = None,
	) -> str:
		"""Read agent definitions — fetch one agent or list all visible agents.

		Behaviour depends on which fields you provide:

		- name_or_id omitted → lists all agents visible to the current user
		  (own agents and shared agents), with name, owner, shared, and description.
		- name_or_id provided → returns full details for that agent, including
		  system_prompt and knowledge_tags.

		**Agent Q&A flow** (use after fetching a specific agent):
		1. agent_read(name) → system_prompt, knowledge_tags
		2. Search the agent's knowledge. Always search the agent:<name> baseline:
		   knowledge_search(query, tag="agent:<name>"). If knowledge_tags is
		   non-empty, run one additional knowledge_search per listed tag and merge
		   the results. Most agents leave knowledge_tags empty and rely on the
		   baseline alone.
		3. knowledge_read(id=...) for entries worth reading
		4. docs_search / docs_read if CHM documentation is relevant
		5. Answer using system_prompt as persona
		6. knowledge_write(tags=["agent:<name>"]) to persist new facts

		Args:
		    name_or_id: Agent name or UUID. Omit to list all visible agents.
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

		return json.dumps(agent.to_dict(), indent=2)

	# ── Write ────────────────────────────────────────────────────────────────────

	@mcp.tool
	async def agent_write(
		mode: Literal["create", "update"],
		name_or_id: str | None = None,
		name: str | None = None,
		description: str | None = None,
		system_prompt: str | None = None,
		knowledge_tags: list[str] | None = None,
		shared: bool | None = None,
	) -> str:
		"""Create or update an agent definition. Authentication required. Owner-only writes.

		Use mode="create" to define a new agent, mode="update" to modify an existing one.

		mode="create": name, description, and system_prompt are required; name_or_id must
		  be omitted; shared defaults to false.

		mode="update": name_or_id is required; all other fields are partial overrides
		  (omit to keep current value); only the agent owner may update.

		To attach knowledge to an agent, use knowledge_write with tags=["agent:<name>"].

		Args:
		    mode: "create" to add a new agent, "update" to modify an existing one.
		    name_or_id: Agent name or UUID. Required for update; omit for create.
		    name: Agent slug (e.g. "omnitracker"). Required for create.
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
				knowledge_tags=knowledge_tags,
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
				knowledge_tags=knowledge_tags,
				shared=shared,
			)

		else:
			return json.dumps({"error": f"Unknown mode '{mode}'. Use 'create' or 'update'."})

		return json.dumps(agent.to_dict(), indent=2)

	# ── Delete ───────────────────────────────────────────────────────────────────

	@mcp.tool
	async def agent_delete(name_or_id: str) -> str:
		"""Delete an agent. Owner-only.

		Deletes the agent definition entirely. Knowledge entries tagged to the
		agent (agent:<name>) are stored independently and are NOT deleted when
		the agent is deleted. Remove them explicitly with knowledge_delete if
		they are no longer needed.

		Args:
		    name_or_id: Agent name or UUID.
		"""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to delete agents.")
		await agent_store.migrate()

		await agent_store.delete(name_or_id, owner=user)
		return json.dumps({"deleted": name_or_id})
