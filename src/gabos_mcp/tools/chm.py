"""MCP tools for searching and reading documentation from CHM help files."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from platformdirs import user_cache_path

from gabos_mcp.extractors.chm import ChmExtractor

if TYPE_CHECKING:
	from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
	"""Register docs tools on the given FastMCP instance."""
	apps = json.loads(os.environ.get("GABOS_CHM_FILES", "{}"))
	cache_dir = os.environ.get("GABOS_CHM_CACHE_DIR", str(user_cache_path("gabos-mcp") / "chm"))
	extractor = ChmExtractor(apps=apps, cache_dir=cache_dir)

	@mcp.tool
	def docs_search(query: str, app: str | None = None, source: str | None = None, limit: int = 30) -> str:
		"""Search documentation pages matching a query.

		Returns JSON array of results with app, source, title, path, and score.
		Use app, source, and path with docs_read_page to read the full content.
		Optionally scope to a specific app and/or source.
		"""
		results = extractor.search(query, app=app, source=source, limit=limit)
		if not results:
			return json.dumps({"message": "No results found."})
		return json.dumps(results, indent=2)

	@mcp.tool
	def docs_read_page(app: str, source: str, path: str) -> str:
		"""Read the full Markdown content of a documentation page.

		Use app, source, and path values returned by docs_search or docs_list_pages.
		"""
		return extractor.read_page(app, source, path)

	@mcp.tool
	def docs_list_pages(app: str, source: str, limit: int = 50, offset: int = 0) -> str:
		"""List available pages in a documentation source with pagination.

		Returns JSON array of pages with title and path.
		Use app, source, and path with docs_read_page to read the full content.
		"""
		pages = extractor.list_pages(app, source, limit=limit, offset=offset)
		if not pages:
			return json.dumps({"message": "No pages found."})
		return json.dumps(pages, indent=2)

	@mcp.tool
	def docs_list_apps() -> str:
		"""List all configured documentation applications."""
		apps = extractor.list_apps()
		if not apps:
			return json.dumps({"message": "No apps configured. Set the GABOS_CHM_FILES environment variable."})
		return json.dumps(apps, indent=2)

	@mcp.tool
	def docs_list_sources(app: str) -> str:
		"""List available documentation sources for a specific application."""
		sources = extractor.list_sources(app)
		if not sources:
			return json.dumps({"message": f"No sources found for app '{app}'."})
		return json.dumps(sources, indent=2)

	@mcp.tool
	def docs_clear_cache(app: str | None = None, source: str | None = None) -> str:
		"""Clear the documentation cache so it will be rebuilt on next access.

		Useful when a CHM file has been updated or a source has been removed.
		Optionally scope to a specific app and/or source; omit both to clear all.
		"""
		cleared = extractor.clear_cache(app=app, source=source)
		if not cleared:
			return json.dumps({"message": "Nothing to clear — no cached data found."})
		return json.dumps({"cleared": cleared})
