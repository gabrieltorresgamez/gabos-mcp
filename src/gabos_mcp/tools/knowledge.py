"""MCP tools and resources for the shared knowledge store."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from gabos_mcp.utils.auth import get_github_login
from gabos_mcp.utils.stores import get_agent_store, get_knowledge_store

if TYPE_CHECKING:
	from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
	"""Register knowledge tools and resources on the given FastMCP instance."""
	store = get_knowledge_store()
	agent_store = get_agent_store()

	@mcp.tool
	async def knowledge_add(
		title: str,
		content: str,
		tags: list[str] | None = None,
		shared: bool = False,
	) -> str:
		"""Add a new knowledge entry. Any authenticated user can add knowledge.

		Args:
		    title: Short title for the entry.
		    content: Markdown content.
		    tags: Optional list of tags.
		    shared: Whether the entry is visible to all authenticated users (default: false).
		"""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to add knowledge.")
		await store.migrate()
		entry = await store.add(owner=user, title=title, content=content, tags=tags, shared=shared)
		return json.dumps(entry, indent=2)

	@mcp.tool
	async def knowledge_get(id: str) -> str:
		"""Get a single knowledge entry by ID."""
		user = get_github_login()
		await store.migrate()
		entry = await store.get(id)
		if entry is None:
			raise KeyError(f"Knowledge entry '{id}' not found.")
		if user != "anonymous" and entry["owner"] != user and not entry.get("shared"):
			raise PermissionError(f"Knowledge entry '{id}' not found or access denied.")
		return json.dumps(entry, indent=2)

	@mcp.tool
	async def knowledge_list(
		owner: str | None = None,
		tag: str | None = None,
		limit: int = 50,
		offset: int = 0,
	) -> str:
		"""List knowledge entries visible to the current user.

		Returns own entries and shared entries from other users, optionally
		filtered by owner or tag.

		Args:
		    owner: Filter to entries from this specific owner (only shows their visible entries).
		    tag: Filter to entries containing this tag.
		    limit: Maximum number of results.
		    offset: Number of entries to skip.
		"""
		user = get_github_login()
		caller = None if user == "anonymous" else user
		await store.migrate()
		entries = await store.list_entries(owner=owner, tag=tag, limit=limit, offset=offset, caller=caller)
		return json.dumps(entries, indent=2)

	@mcp.tool
	async def knowledge_update(
		id: str,
		title: str | None = None,
		content: str | None = None,
		tags: list[str] | None = None,
		shared: bool | None = None,
	) -> str:
		"""Update a knowledge entry. Only the owner can edit their own entries.

		Args:
		    id: Entry ID.
		    title: New title, or omit to keep existing.
		    content: New content, or omit to keep existing.
		    tags: New tags, or omit to keep existing.
		    shared: Set to true to share with all users, false to make private.
		"""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to edit knowledge.")
		await store.migrate()
		entry = await store.update(id=id, owner=user, title=title, content=content, tags=tags, shared=shared)
		return json.dumps(entry, indent=2)

	@mcp.tool
	async def knowledge_delete(id: str) -> str:
		"""Delete a knowledge entry.

		Permission rules:
		- The entry's owner can always delete it.
		- An agent owner can delete a shared entry tagged to their agent:
		  - If the entry is tagged only to agents the caller owns → delete entirely.
		  - If tagged to agents owned by multiple users → remove only the caller's agent tags.
		- All other users are denied.
		"""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to delete knowledge.")
		await store.migrate()
		entry = await store.get(id)
		if entry is None:
			raise KeyError(f"Knowledge entry '{id}' not found.")

		# Owner always deletes normally.
		if entry["owner"] == user:
			await store.delete(id=id, owner=user)
			return json.dumps({"deleted": id})

		# Non-owner: entry must be visible to them.
		if not entry.get("shared"):
			raise PermissionError("You can only delete your own knowledge entries.")

		# Check if caller owns any agent referenced by this entry's tags.
		# Agent tags have the form "agent:<name>" (not "agent:<name>:folder:<key>").
		agent_tags = [t for t in entry["tags"] if t.startswith("agent:") and t.count(":") == 1]
		if not agent_tags:
			raise PermissionError("You can only delete your own knowledge entries.")

		await agent_store.migrate()
		caller_tags: list[str] = []
		other_user_has_tagged_agent = False
		for tag in agent_tags:
			agent_name = tag[len("agent:") :]
			agent_obj = await agent_store.get(agent_name)
			if agent_obj is not None:
				if agent_obj.owner == user:
					caller_tags.append(tag)
				else:
					other_user_has_tagged_agent = True

		if not caller_tags:
			raise PermissionError("You can only delete your own knowledge entries.")

		if other_user_has_tagged_agent:
			# Other users own agents also tagged — only remove caller's agent tags.
			await store.remove_tags(id, caller_tags)
			return json.dumps({"untagged": id, "removed_tags": caller_tags})
		# All tagged agents belong to caller → delete the entry entirely.
		await store.delete_unchecked(id)
		return json.dumps({"deleted": id})

	@mcp.resource("knowledge://list")
	async def knowledge_list_resource() -> str:
		"""Knowledge entries visible to the current user (id, owner, title, tags, updated_at)."""
		user = get_github_login()
		caller = None if user == "anonymous" else user
		await store.migrate()
		entries = await store.list_entries(limit=1000, caller=caller)
		summary = [{k: v for k, v in e.items() if k != "content"} for e in entries]
		return json.dumps(summary, indent=2)

	@mcp.resource("knowledge://{id}")
	async def knowledge_entry(id: str) -> str:
		"""Full content of a single knowledge entry."""
		user = get_github_login()
		await store.migrate()
		entry = await store.get(id)
		if entry is None:
			raise KeyError(f"Knowledge entry '{id}' not found.")
		if user != "anonymous" and entry["owner"] != user and not entry.get("shared"):
			raise PermissionError(f"Knowledge entry '{id}' not found or access denied.")
		return json.dumps(entry, indent=2)
