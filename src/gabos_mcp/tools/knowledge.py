"""MCP tools and resources for the shared knowledge store."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from gabos_mcp.utils.auth import get_github_login
from gabos_mcp.utils.stores import get_knowledge_store

if TYPE_CHECKING:
	from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
	"""Register knowledge tools and resources on the given FastMCP instance."""
	store = get_knowledge_store()

	@mcp.tool
	async def knowledge_add(title: str, content: str, tags: list[str] | None = None) -> str:
		"""Add a new knowledge entry. Any authenticated user can add knowledge."""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to add knowledge.")
		await store.migrate()
		entry = await store.add(owner=user, title=title, content=content, tags=tags)
		return json.dumps(entry, indent=2)

	@mcp.tool
	async def knowledge_get(id: str) -> str:
		"""Get a single knowledge entry by ID."""
		await store.migrate()
		entry = await store.get(id)
		if entry is None:
			raise KeyError(f"Knowledge entry '{id}' not found.")
		return json.dumps(entry, indent=2)

	@mcp.tool
	async def knowledge_list(
		owner: str | None = None,
		tag: str | None = None,
		limit: int = 50,
		offset: int = 0,
	) -> str:
		"""List knowledge entries, optionally filtered by owner or tag."""
		await store.migrate()
		entries = await store.list_entries(owner=owner, tag=tag, limit=limit, offset=offset)
		return json.dumps(entries, indent=2)

	@mcp.tool
	async def knowledge_update(
		id: str,
		title: str | None = None,
		content: str | None = None,
		tags: list[str] | None = None,
	) -> str:
		"""Update a knowledge entry. Only the owner can edit their own entries."""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to edit knowledge.")
		await store.migrate()
		entry = await store.update(id=id, owner=user, title=title, content=content, tags=tags)
		return json.dumps(entry, indent=2)

	@mcp.tool
	async def knowledge_delete(id: str) -> str:
		"""Delete a knowledge entry. Only the owner can delete their own entries."""
		user = get_github_login()
		if user == "anonymous":
			raise PermissionError("Authentication required to delete knowledge.")
		await store.migrate()
		await store.delete(id=id, owner=user)
		return json.dumps({"deleted": id})

	@mcp.resource("knowledge://list")
	async def knowledge_list_resource() -> str:
		"""All knowledge entries (id, owner, title, tags, updated_at) — content excluded."""
		await store.migrate()
		entries = await store.list_entries(limit=1000)
		summary = [{k: v for k, v in e.items() if k != "content"} for e in entries]
		return json.dumps(summary, indent=2)

	@mcp.resource("knowledge://{id}")
	async def knowledge_entry(id: str) -> str:
		"""Full content of a single knowledge entry."""
		await store.migrate()
		entry = await store.get(id)
		if entry is None:
			raise KeyError(f"Knowledge entry '{id}' not found.")
		return json.dumps(entry, indent=2)
