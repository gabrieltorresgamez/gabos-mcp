"""MCP tools for searching and reading documentation from CHM help files."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from platformdirs import user_cache_path

from gabos_mcp.extractors.chm import ChmExtractor

if TYPE_CHECKING:
	from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:  # noqa: C901
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
	async def docs_read(  # noqa: PLR0911
		app: str | None = None,
		source: str | None = None,
		page_path: str | None = None,
		limit: int = 50,
		offset: int = 0,
	) -> str:
		"""Read documentation structure or content.

		Behaviour depends on which fields you provide:

		- No fields → returns list of configured application names.
		- app only → returns list of sources within that app.
		- app + source → returns list of pages in that source (paginated via limit/offset).
		- app + source + page_path → returns the full Markdown content of that page.

		Use docs_search for free-text queries — this tool is for navigation and exact-path
		retrieval, not full-text search.

		Invalid combinations (e.g. page_path without source, source without app) return an
		error message describing the expected fields.

		Args:
		    app: Application name (e.g. "OMNITRACKER"). Omit to list all apps.
		    source: Source name within the app. Requires app.
		    page_path: Page path within the source. Requires app and source.
		    limit: Max pages to return when listing (ignored when reading a page).
		    offset: Pages to skip when listing (ignored when reading a page).
		"""
		# Validate field combinations
		if page_path and not source:
			return json.dumps(
				{
					"error": "page_path requires source. "
					"Provide app + source + page_path to read a page, or app + source to list pages."
				}
			)
		if source and not app:
			return json.dumps(
				{
					"error": "source requires app. "
					"Provide app + source to list pages, or app + source + page_path to read a page."
				}
			)

		if app is None:
			# List all apps
			apps_list = extractor.list_apps()
			if not apps_list:
				return json.dumps({"message": "No apps configured. Set the GABOS_CHM_FILES environment variable."})
			return json.dumps(apps_list, indent=2)

		if source is None:
			# List sources within app
			sources = extractor.list_sources(app)
			if not sources:
				return json.dumps({"message": f"No sources found for app '{app}'."})
			return json.dumps(sources, indent=2)

		if page_path is None:
			# List pages within source
			pages = await extractor.list_pages(app, source, limit=limit, offset=offset)
			if not pages:
				return json.dumps({"message": f"No pages found in '{app}/{source}'."})
			return json.dumps(pages, indent=2)

		# Read page content
		return await extractor.read_page(app, source, page_path)
