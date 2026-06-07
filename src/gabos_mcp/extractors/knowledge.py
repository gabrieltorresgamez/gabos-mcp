"""SQLite-backed shared knowledge store."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite


def _now() -> str:
	return datetime.now(UTC).isoformat()


class KnowledgeStore:
	"""Persistent knowledge store backed by SQLite.

	Any authenticated user can add entries and read visible entries.
	Visibility: owner sees their own entries; others see entries where shared=True.
	Only the owner of an entry can update or delete it (with agent-owner exceptions
	handled at the tool layer).
	"""

	def __init__(self, db_path: str) -> None:
		"""Initialize with the path to the SQLite database file (created if absent)."""
		self._db_path = Path(db_path).expanduser()
		self._db_path.parent.mkdir(parents=True, exist_ok=True)
		self._conn: aiosqlite.Connection | None = None
		self._migrated = False

	async def _connect(self) -> aiosqlite.Connection:
		if self._conn is None:
			self._conn = await aiosqlite.connect(str(self._db_path))
			self._conn.row_factory = aiosqlite.Row
		return self._conn

	async def _column_exists(self, table: str, column: str) -> bool:
		conn = await self._connect()
		cursor = await conn.execute(f"SELECT COUNT(*) FROM pragma_table_info('{table}') WHERE name = ?", (column,))
		row = await cursor.fetchone()
		return bool(row and row[0] > 0)

	async def migrate(self) -> None:
		"""Create the necessary database tables if they do not exist."""
		if self._migrated:
			return
		conn = await self._connect()
		await conn.execute("""
			CREATE TABLE IF NOT EXISTS knowledge (
				id         TEXT PRIMARY KEY,
				owner      TEXT NOT NULL,
				title      TEXT NOT NULL,
				content    TEXT NOT NULL,
				tags       TEXT NOT NULL DEFAULT '[]',
				shared     INTEGER NOT NULL DEFAULT 0,
				created_at TEXT NOT NULL,
				updated_at TEXT NOT NULL
			)
		""")
		if not await self._column_exists("knowledge", "shared"):
			await conn.execute("ALTER TABLE knowledge ADD COLUMN shared INTEGER NOT NULL DEFAULT 0")
		await conn.execute("""
			CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
			USING fts5(id UNINDEXED, title, content,
			           tokenize='trigram', content='knowledge', content_rowid='rowid')
		""")
		await conn.execute("""
			CREATE TRIGGER IF NOT EXISTS knowledge_fts_insert
			AFTER INSERT ON knowledge BEGIN
				INSERT INTO knowledge_fts(rowid, id, title, content)
				VALUES (new.rowid, new.id, new.title, new.content);
			END
		""")
		await conn.execute("""
			CREATE TRIGGER IF NOT EXISTS knowledge_fts_update
			AFTER UPDATE ON knowledge BEGIN
				INSERT INTO knowledge_fts(knowledge_fts, rowid, id, title, content)
				VALUES ('delete', old.rowid, old.id, old.title, old.content);
				INSERT INTO knowledge_fts(rowid, id, title, content)
				VALUES (new.rowid, new.id, new.title, new.content);
			END
		""")
		await conn.execute("""
			CREATE TRIGGER IF NOT EXISTS knowledge_fts_delete
			AFTER DELETE ON knowledge BEGIN
				INSERT INTO knowledge_fts(knowledge_fts, rowid, id, title, content)
				VALUES ('delete', old.rowid, old.id, old.title, old.content);
			END
		""")
		# Populate FTS index for any existing rows (idempotent rebuild).
		await conn.execute("INSERT INTO knowledge_fts(knowledge_fts) VALUES('rebuild')")
		await conn.commit()
		self._migrated = True

	@staticmethod
	def _row_to_dict(row: aiosqlite.Row) -> dict:
		d = dict(row)
		d["tags"] = json.loads(str(d["tags"]))
		d["shared"] = bool(d.get("shared"))
		return d

	async def search(
		self,
		query: str,
		tag: str | None = None,
		owner: str | None = None,
		limit: int = 10,
		offset: int = 0,
		caller: str | None = None,
	) -> list[dict]:
		"""Full-text search over knowledge entries, ranked by relevance.

		Args:
		    query: Search terms (FTS5 trigram match).
		    tag: Optional tag to restrict results to.
		    owner: Optional owner login to restrict results to.
		    limit: Maximum number of results.
		    offset: Number of results to skip.
		    caller: If provided, restrict to entries visible to this user
		            (own entries or shared entries).

		Returns:
		    List of entry dicts ordered by relevance (best first), each including
		    a ``score`` field (FTS5 BM25 rank; lower/more negative = better match).
		"""
		fts_query = re.sub(r"[^\w\s]", " ", query).strip() or '""'
		conn = await self._connect()

		visibility_clause = ""
		visibility_params: list[str] = []
		if caller is not None:
			visibility_clause = "AND (k.owner = ? OR k.shared = 1) "
			visibility_params = [caller]

		owner_clause = ""
		owner_params: list[str] = []
		if owner is not None:
			owner_clause = "AND k.owner = ? "
			owner_params = [owner]

		if tag:
			cursor = await conn.execute(
				"SELECT k.*, knowledge_fts.rank AS score FROM knowledge_fts "
				"JOIN knowledge k ON knowledge_fts.rowid = k.rowid "
				"WHERE knowledge_fts MATCH ? "
				+ visibility_clause
				+ owner_clause
				+ "AND EXISTS (SELECT 1 FROM json_each(k.tags) jt WHERE jt.value = ?) "
				"ORDER BY knowledge_fts.rank LIMIT ? OFFSET ?",
				(fts_query, *visibility_params, *owner_params, tag, limit, offset),
			)
		else:
			cursor = await conn.execute(
				"SELECT k.*, knowledge_fts.rank AS score FROM knowledge_fts "
				"JOIN knowledge k ON knowledge_fts.rowid = k.rowid "
				"WHERE knowledge_fts MATCH ? "
				+ visibility_clause
				+ owner_clause
				+ "ORDER BY knowledge_fts.rank LIMIT ? OFFSET ?",
				(fts_query, *visibility_params, *owner_params, limit, offset),
			)
		rows = await cursor.fetchall()
		return [self._row_to_dict(r) for r in rows]

	async def add(
		self,
		owner: str,
		title: str,
		content: str,
		tags: list[str] | None = None,
		shared: bool = False,
	) -> dict:
		"""Create a new knowledge entry.

		Args:
		    owner: GitHub login of the creator.
		    title: Short title for the entry.
		    content: Markdown content.
		    tags: Optional list of tags.
		    shared: Whether the entry is readable by all authenticated users.

		Returns:
		    The created entry as a dict.
		"""
		now = _now()
		entry_id = str(uuid.uuid4())
		tags_list = tags or []
		conn = await self._connect()
		await conn.execute(
			"INSERT INTO knowledge (id, owner, title, content, tags, shared, created_at, updated_at) "
			"VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
			(entry_id, owner, title, content, json.dumps(tags_list), 1 if shared else 0, now, now),
		)
		await conn.commit()
		return {
			"id": entry_id,
			"owner": owner,
			"title": title,
			"content": content,
			"tags": tags_list,
			"shared": shared,
			"created_at": now,
			"updated_at": now,
		}

	async def get(self, id: str, caller: str | None = None) -> dict | None:
		"""Return a single entry by ID, or None if not found.

		Args:
		    id: Entry UUID.
		    caller: If provided, raises PermissionError when the entry exists but
		            is private and not owned by this caller.

		Raises:
		    PermissionError: If the entry exists but is not visible to caller.
		"""
		conn = await self._connect()
		cursor = await conn.execute("SELECT * FROM knowledge WHERE id = ?", (id,))
		row = await cursor.fetchone()
		if row is None:
			return None
		entry = self._row_to_dict(row)
		if caller is not None and entry["owner"] != caller and not entry.get("shared"):
			raise PermissionError(f"Knowledge entry '{id}' not found or access denied.")
		return entry

	async def update(
		self,
		id: str,
		owner: str,
		title: str | None = None,
		content: str | None = None,
		tags: list[str] | None = None,
		shared: bool | None = None,
	) -> dict:
		"""Update an existing entry. Only the owner may update.

		Args:
		    id: Entry ID.
		    owner: GitHub login of the caller.
		    title: New title, or None to keep existing.
		    content: New content, or None to keep existing.
		    tags: New tags, or None to keep existing.
		    shared: New shared flag, or None to keep existing.

		Returns:
		    The updated entry as a dict.

		Raises:
		    KeyError: If the entry does not exist.
		    PermissionError: If the caller is not the owner.
		"""
		entry = await self.get(id)
		if entry is None:
			raise KeyError(f"Knowledge entry '{id}' not found.")
		if entry["owner"] != owner:
			raise PermissionError("You can only edit your own knowledge entries.")

		new_title = title if title is not None else entry["title"]
		new_content = content if content is not None else entry["content"]
		new_tags = tags if tags is not None else entry["tags"]
		new_shared = shared if shared is not None else entry["shared"]
		now = _now()

		conn = await self._connect()
		await conn.execute(
			"UPDATE knowledge SET title = ?, content = ?, tags = ?, shared = ?, updated_at = ? WHERE id = ?",
			(new_title, new_content, json.dumps(new_tags), 1 if new_shared else 0, now, id),
		)
		await conn.commit()

		return {
			**entry,
			"title": new_title,
			"content": new_content,
			"tags": new_tags,
			"shared": new_shared,
			"updated_at": now,
		}

	async def delete(self, id: str, owner: str) -> None:
		"""Delete an entry. Only the owner may delete.

		Args:
		    id: Entry ID.
		    owner: GitHub login of the caller.

		Raises:
		    KeyError: If the entry does not exist.
		    PermissionError: If the caller is not the owner.
		"""
		entry = await self.get(id)
		if entry is None:
			raise KeyError(f"Knowledge entry '{id}' not found.")
		if entry["owner"] != owner:
			raise PermissionError("You can only delete your own knowledge entries.")

		conn = await self._connect()
		await conn.execute("DELETE FROM knowledge WHERE id = ?", (id,))
		await conn.commit()

	async def close(self) -> None:
		"""Close the database connection and release the background thread."""
		if self._conn is not None:
			await self._conn.close()
			self._conn = None
