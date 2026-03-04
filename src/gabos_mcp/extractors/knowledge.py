"""SQLite-backed shared knowledge store."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path


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
		self._migrate()

	def _connect(self) -> sqlite3.Connection:
		conn = sqlite3.connect(str(self._db_path))
		conn.row_factory = sqlite3.Row
		return conn

	def _migrate(self) -> None:
		with self._connect() as conn:
			conn.execute("""
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

	@staticmethod
	def _row_to_dict(row: sqlite3.Row) -> dict:
		d = dict(row)
		d["tags"] = json.loads(str(d["tags"]))
		return d

	def add(self, owner: str, title: str, content: str, tags: list[str] | None = None) -> dict:
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
		with self._connect() as conn:
			conn.execute(
				"INSERT INTO knowledge (id, owner, title, content, tags, created_at, updated_at) "
				"VALUES (?, ?, ?, ?, ?, ?, ?)",
				(entry_id, owner, title, content, json.dumps(tags_list), now, now),
			)
		return {
			"id": entry_id,
			"owner": owner,
			"title": title,
			"content": content,
			"tags": tags_list,
			"created_at": now,
			"updated_at": now,
		}

	def get(self, id: str) -> dict | None:
		"""Return a single entry by ID, or None if not found."""
		with self._connect() as conn:
			row = conn.execute("SELECT * FROM knowledge WHERE id = ?", (id,)).fetchone()
		return self._row_to_dict(row) if row else None

	def list_entries(
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
		with self._connect() as conn:
			if owner:
				rows = conn.execute(
					"SELECT * FROM knowledge WHERE owner = ? ORDER BY updated_at DESC",
					(owner,),
				).fetchall()
			else:
				rows = conn.execute("SELECT * FROM knowledge ORDER BY updated_at DESC").fetchall()

		results = [self._row_to_dict(r) for r in rows]
		if tag:
			results = [r for r in results if tag in r["tags"]]
		return results[offset : offset + limit]

	def update(
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
		entry = self.get(id)
		if entry is None:
			raise KeyError(f"Knowledge entry '{id}' not found.")
		if entry["owner"] != owner:
			raise PermissionError("You can only edit your own knowledge entries.")

		new_title = title if title is not None else entry["title"]
		new_content = content if content is not None else entry["content"]
		new_tags = tags if tags is not None else entry["tags"]
		now = _now()

		with self._connect() as conn:
			conn.execute(
				"UPDATE knowledge SET title = ?, content = ?, tags = ?, updated_at = ? WHERE id = ?",
				(new_title, new_content, json.dumps(new_tags), now, id),
			)

		return {**entry, "title": new_title, "content": new_content, "tags": new_tags, "updated_at": now}

	def delete(self, id: str, owner: str) -> None:
		"""Delete an entry. Only the owner may delete.

		Args:
		    id: Entry ID.
		    owner: GitHub login of the caller.

		Raises:
		    KeyError: If the entry does not exist.
		    PermissionError: If the caller is not the owner.
		"""
		entry = self.get(id)
		if entry is None:
			raise KeyError(f"Knowledge entry '{id}' not found.")
		if entry["owner"] != owner:
			raise PermissionError("You can only delete your own knowledge entries.")

		with self._connect() as conn:
			conn.execute("DELETE FROM knowledge WHERE id = ?", (id,))
