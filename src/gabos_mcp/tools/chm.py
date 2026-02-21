"""MCP tools for searching and reading CHM help files."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from gabos_mcp.extractors.chm import ChmExtractor

if TYPE_CHECKING:
    from fastmcp import FastMCP

_apps = json.loads(os.environ.get("GABOS_CHM_FILES", "{}"))
_cache_dir = os.environ.get("GABOS_CHM_CACHE_DIR", "~/.cache/gabos-mcp/chm")
_extractor = ChmExtractor(apps=_apps, cache_dir=_cache_dir)


def register(mcp: FastMCP) -> None:
    """Register CHM tools on the given FastMCP instance."""

    @mcp.tool
    def search_chm(query: str, app: str | None = None, source: str | None = None, limit: int = 10) -> str:
        """Search CHM help files for pages matching a query.

        Returns JSON array of results with app, source, title, path, and score.
        Use app, source, and path with read_chm_page to read the full content.
        Optionally scope to a specific app and/or source.
        """
        results = _extractor.search(query, app=app, source=source, limit=limit)
        if not results:
            return json.dumps({"message": "No results found."})
        return json.dumps(results, indent=2)

    @mcp.tool
    def read_chm_page(app: str, source: str, path: str) -> str:
        """Read the full Markdown content of a CHM page.

        Use app, source, and path values returned by search_chm.
        """
        return _extractor.read_page(app, source, path)

    @mcp.tool
    def list_chm_pages(app: str, source: str, limit: int = 50, offset: int = 0) -> str:
        """List available pages in a CHM source with pagination.

        Returns JSON array of pages with title and path.
        Use app, source, and path with read_chm_page to read the full content.
        """
        pages = _extractor.list_pages(app, source, limit=limit, offset=offset)
        if not pages:
            return json.dumps({"message": "No pages found."})
        return json.dumps(pages, indent=2)

    @mcp.tool
    def list_chm_apps() -> str:
        """List all configured applications that have CHM help files."""
        apps = _extractor.list_apps()
        if not apps:
            return json.dumps({"message": "No apps configured. Set the GABOS_CHM_FILES environment variable."})
        return json.dumps(apps, indent=2)

    @mcp.tool
    def list_chm_sources(app: str) -> str:
        """List available CHM sources for a specific application."""
        sources = _extractor.list_sources(app)
        if not sources:
            return json.dumps({"message": f"No sources found for app '{app}'."})
        return json.dumps(sources, indent=2)
