"""Generic full-text search index backed by SQLite FTS5."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import aiosqlite

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
		self._conn: aiosqlite.Connection | None = None

	async def _connect(self) -> aiosqlite.Connection:
		if self._conn is None:
			self._conn = await aiosqlite.connect(self._db_path)
		return self._conn

	async def build(self, documents: Iterable[tuple[str, str, str]]) -> None:
		"""Build the search index from documents.

		A marker file prevents rebuilding if the index already exists. Delete
		the marker to force a rebuild.

		Args:
		    documents: Iterable of (path, title, content) tuples.
		"""
		if self._marker.exists():
			return

		self._index_dir.mkdir(parents=True, exist_ok=True)

		con = await self._connect()
		try:
			await con.execute("PRAGMA synchronous = OFF;")
			await con.execute("PRAGMA journal_mode = MEMORY;")
			await con.execute(f"DROP TABLE IF EXISTS {_TABLE}")
			await con.execute(
				f'CREATE VIRTUAL TABLE {_TABLE} USING fts5(path UNINDEXED, title, content, tokenize="trigram")'
			)

			batch = []
			for path, title, content in documents:
				batch.append((path, title, content))
				if len(batch) >= 1000:
					try:
						await con.executemany(f"INSERT INTO {_TABLE}(path, title, content) VALUES (?, ?, ?)", batch)
					except Exception:
						logger.warning("Failed to index a batch of documents, skipping", exc_info=True)
					batch.clear()

			if batch:
				try:
					await con.executemany(f"INSERT INTO {_TABLE}(path, title, content) VALUES (?, ?, ?)", batch)
				except Exception:
					logger.warning("Failed to index a batch of documents, skipping", exc_info=True)

			await con.commit()
		except Exception:
			logger.warning("Failed to build index", exc_info=True)

		self._marker.touch()

	async def search(self, query: str, limit: int = 10) -> list[dict]:
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

		con = await self._connect()
		try:
			cursor = await con.execute(
				f"SELECT path, title, bm25({_TABLE}) FROM {_TABLE}"
				f" WHERE {_TABLE} MATCH ?"
				f" ORDER BY bm25({_TABLE}) LIMIT ?",
				(query, limit),
			)
			rows = await cursor.fetchall()
		except Exception:
			logger.warning("Failed to parse query: %s", query)
			return []

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

	async def list_documents(self, limit: int = 50, offset: int = 0) -> list[dict]:
		"""List all indexed documents, ordered by path.

		Args:
		    limit: Maximum number of results to return.
		    offset: Number of results to skip.

		Returns:
		    List of dicts with keys: title, path.
		"""
		if not self._db_path.exists():
			return []

		con = await self._connect()
		cursor = await con.execute(
			f"SELECT path, title FROM {_TABLE} ORDER BY path LIMIT ? OFFSET ?",
			(limit, offset),
		)
		rows = await cursor.fetchall()

		return [{"title": title, "path": path} for path, title in rows]
