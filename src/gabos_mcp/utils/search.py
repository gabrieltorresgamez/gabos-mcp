"""Generic full-text search index backed by Whoosh."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from whoosh.fields import ID, TEXT, Schema
from whoosh.index import create_in, exists_in, open_dir
from whoosh.qparser import MultifieldParser

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

logger = logging.getLogger(__name__)


class SearchIndex:
    """Full-text search index over arbitrary text documents.

    Callers are responsible for producing (path, title, content) tuples from
    their source files. This class handles only indexing and querying.
    """

    def __init__(self, index_dir: Path) -> None:
        """Initialize with the directory where the Whoosh index will be stored."""
        self._index_dir = index_dir
        self._marker = index_dir / ".indexed"

    def build(self, documents: Iterable[tuple[str, str, str]]) -> None:
        """Build the search index from documents.

        A marker file prevents rebuilding if the index already exists. Delete
        the marker to force a rebuild.

        Args:
            documents: Iterable of (path, title, content) tuples.
        """
        if self._marker.exists():
            return

        self._index_dir.mkdir(parents=True, exist_ok=True)

        schema = Schema(
            path=ID(stored=True, unique=True),
            title=TEXT(stored=True),
            content=TEXT,
        )
        ix = create_in(str(self._index_dir), schema)
        writer = ix.writer()

        for path, title, content in documents:
            try:
                writer.add_document(path=path, title=title, content=content)
            except Exception:
                logger.warning("Failed to index document %s, skipping", path, exc_info=True)

        writer.commit()
        self._marker.touch()

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search the index.

        Args:
            query: Full-text search query.
            limit: Maximum number of results.

        Returns:
            List of dicts with keys: title, path, score. Sorted by score descending.
            Returns an empty list if the index does not exist or the query fails to parse.
        """
        if not exists_in(str(self._index_dir)):
            return []

        ix = open_dir(str(self._index_dir))
        with ix.searcher() as searcher:
            parser = MultifieldParser(["title", "content"], ix.schema)
            try:
                parsed = parser.parse(query)
            except Exception:
                logger.warning("Failed to parse query: %s", query)
                return []

            hits = searcher.search(parsed, limit=limit)
            results = [
                {
                    "title": hit["title"],
                    "path": hit["path"],
                    "score": round(hit.score, 2),
                }
                for hit in hits
            ]

        results.sort(key=lambda r: r["score"], reverse=True)
        return results
