"""Generic full-text search index backed by SQLite FTS5."""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

logger = logging.getLogger(__name__)

_DB_FILE = "index.db"
_TABLE = "docs"


class SearchIndex:
    """Full-text search index over arbitrary text documents.

    Callers are responsible for producing (path, title, content) tuples from
    their source files. This class handles only indexing and querying.
    """

    def __init__(self, index_dir: Path) -> None:
        """Initialize with the directory where the SQLite index will be stored."""
        self._index_dir = index_dir
        self._marker = index_dir / ".indexed"
        self._db_path = index_dir / _DB_FILE

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

        con = sqlite3.connect(self._db_path)
        try:
            con.execute(f"DROP TABLE IF EXISTS {_TABLE}")
            con.execute(f"CREATE VIRTUAL TABLE {_TABLE} USING fts5(path UNINDEXED, title, content)")
            for path, title, content in documents:
                try:
                    con.execute(
                        f"INSERT INTO {_TABLE}(path, title, content) VALUES (?, ?, ?)",
                        (path, title, content),
                    )
                except Exception:
                    logger.warning("Failed to index document %s, skipping", path, exc_info=True)
            con.commit()
        finally:
            con.close()

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
        if not self._db_path.exists():
            return []

        con = sqlite3.connect(self._db_path)
        try:
            try:
                rows = con.execute(
                    f"SELECT path, title, bm25({_TABLE}) FROM {_TABLE}"
                    f" WHERE {_TABLE} MATCH ?"
                    f" ORDER BY bm25({_TABLE}) LIMIT ?",
                    (query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                logger.warning("Failed to parse query: %s", query)
                return []
        finally:
            con.close()

        # bm25() returns negative values — lower is better. Negate and clamp to >= 0.
        results = [
            {
                "title": title,
                "path": path,
                "score": int(max(-score, 0.0) * 100 + 0.5) / 100,
            }
            for path, title, score in rows
        ]
        results.sort(key=lambda r: r["score"], reverse=True)
        return results
