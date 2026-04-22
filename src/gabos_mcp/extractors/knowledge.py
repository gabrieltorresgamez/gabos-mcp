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

	Any authenticated user can add entries and read all entries.
	Only the owner of an entry can update or delete it.
	"""

	def __init__(self, db_path: str) -> None:
		"""Initialize with the path to the SQLite database file (created if absent)."""
		self._db_path = Path(db_path).expanduser()
		self._db_path.parent.mkdir(parents=True, exist_ok=True)
		self._conn: aiosqlite.Connection | None = None

	async def _connect(self) -> aiosqlite.Connection:
		if self._conn is None:
			self._conn = await aiosqlite.connect(str(self._db_path))
			self._conn.row_factory = aiosqlite.Row
		return self._conn

	async def migrate(self) -> None:
		"""Create the necessary database tables if they do not exist."""
		conn = await self._connect()
		await conn.execute("""
			CREATE TABLE IF NOT EXISTS knowledge (
				id         TEXT PRIMARY KEY,
				owner      TEXT NOT NULL,
				title      TEXT NOT NULL,
				content    TEXT NOT NULL,
				tags       TEXT NOT NULL DEFAULT '[]',
				created_at TEXT NOT NULL,
				updated_at TEXT NOT NULL
			)
		""")
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

	@staticmethod
	def _row_to_dict(row: aiosqlite.Row) -> dict:
		d = dict(row)
		d["tags"] = json.loads(str(d["tags"]))
		return d

	async def search(self, query: str, tag: str | None = None, limit: int = 10) -> list[dict]:
		"""Full-text search over knowledge entries, ranked by relevance.

		Args:
		    query: Search terms (FTS5 trigram match).
		    tag: Optional tag to restrict results to.
		    limit: Maximum number of results.

		Returns:
		    List of entry dicts ordered by relevance (best first).
		"""
		fts_query = re.sub(r"[^\w\s]", " ", query).strip() or '""'
		conn = await self._connect()
		if tag:
			cursor = await conn.execute(
				"SELECT k.* FROM knowledge_fts "
				"JOIN knowledge k ON knowledge_fts.rowid = k.rowid "
				"WHERE knowledge_fts MATCH ? "
				"AND EXISTS (SELECT 1 FROM json_each(k.tags) jt WHERE jt.value = ?) "
				"ORDER BY knowledge_fts.rank LIMIT ?",
				(fts_query, tag, limit),
			)
		else:
			cursor = await conn.execute(
				"SELECT k.* FROM knowledge_fts "
				"JOIN knowledge k ON knowledge_fts.rowid = k.rowid "
				"WHERE knowledge_fts MATCH ? ORDER BY knowledge_fts.rank LIMIT ?",
				(fts_query, limit),
			)
		rows = await cursor.fetchall()
		return [self._row_to_dict(r) for r in rows]

	async def add(self, owner: str, title: str, content: str, tags: list[str] | None = None) -> dict:
		"""Create a new knowledge entry.

		Args:
		    owner: GitHub login of the creator.
		    title: Short title for the entry.
		    content: Markdown content.
		    tags: Optional list of tags.

		Returns:
		    The created entry as a dict.
		"""
		now = _now()
		entry_id = str(uuid.uuid4())
		tags_list = tags or []
		conn = await self._connect()
		await conn.execute(
			"INSERT INTO knowledge (id, owner, title, content, tags, created_at, updated_at) "
			"VALUES (?, ?, ?, ?, ?, ?, ?)",
			(entry_id, owner, title, content, json.dumps(tags_list), now, now),
		)
		await conn.commit()
		return {
			"id": entry_id,
			"owner": owner,
			"title": title,
			"content": content,
			"tags": tags_list,
			"created_at": now,
			"updated_at": now,
		}

	async def get(self, id: str) -> dict | None:
		"""Return a single entry by ID, or None if not found."""
		conn = await self._connect()
		cursor = await conn.execute("SELECT * FROM knowledge WHERE id = ?", (id,))
		row = await cursor.fetchone()
		return self._row_to_dict(row) if row else None

	async def list_entries(
		self,
		owner: str | None = None,
		tag: str | None = None,
		limit: int = 50,
		offset: int = 0,
	) -> list[dict]:
		"""List entries, optionally filtered by owner and/or tag.

		Args:
		    owner: Filter to entries owned by this GitHub login.
		    tag: Filter to entries containing this tag.
		    limit: Maximum number of results.
		    offset: Number of entries to skip.

		Returns:
		    List of entry dicts ordered by updated_at descending.
		"""
		conn = await self._connect()
		query = "SELECT DISTINCT knowledge.* FROM knowledge"
		params: list[str | int] = []

		if tag:
			query += ", json_each(knowledge.tags) WHERE json_each.value = ?"
			params.append(tag)
			if owner:
				query += " AND owner = ?"
				params.append(owner)
		else:
			if owner:
				query += " WHERE owner = ?"
				params.append(owner)

		query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
		params.extend([limit, offset])

		cursor = await conn.execute(query, tuple(params))
		rows = await cursor.fetchall()

		return [self._row_to_dict(r) for r in rows]

	async def update(
		self,
		id: str,
		owner: str,
		title: str | None = None,
		content: str | None = None,
		tags: list[str] | None = None,
	) -> dict:
		"""Update an existing entry. Only the owner may update.

		Args:
		    id: Entry ID.
		    owner: GitHub login of the caller.
		    title: New title, or None to keep existing.
		    content: New content, or None to keep existing.
		    tags: New tags, or None to keep existing.

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
		now = _now()

		conn = await self._connect()
		await conn.execute(
			"UPDATE knowledge SET title = ?, content = ?, tags = ?, updated_at = ? WHERE id = ?",
			(new_title, new_content, json.dumps(new_tags), now, id),
		)
		await conn.commit()

		return {**entry, "title": new_title, "content": new_content, "tags": new_tags, "updated_at": now}

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
