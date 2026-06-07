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
	async def docs_search(query: str, app: str | None = None, source: str | None = None, limit: int = 30) -> str:
		"""Search documentation pages matching a query.

		Returns JSON array of results with app, source, title, path, and score.
		Use app, source, and path with docs_read to read the full content.
		Optionally scope to a specific app and/or source.

		Use this tool for free-text queries. To browse apps, sources, or pages by
		path, use docs_read instead.
		"""
		results = await extractor.search(query, app=app, source=source, limit=limit)
		if not results:
			return json.dumps({"message": "No results found."})
		return json.dumps(results, indent=2)

	@mcp.tool
	async def docs_read(
		app: str,
		source: str,
		page_path: str,
	) -> str:
		"""Read the full Markdown content of a documentation page.

		Use docs_search to discover app, source, and page_path values.

		Args:
		    app: Application name (e.g. "OMNITRACKER").
		    source: Source name within the app.
		    page_path: Page path within the source.
		"""
		return await extractor.read_page(app, source, page_path)
