"""SQLite-backed ground-truth schema store (OMNITRACKER Export Documentation)."""

from __future__ import annotations

import json
from typing import Any

import aiosqlite

from gabos_mcp.extractors.base import BaseStore
from gabos_mcp.utils.db import now as _now
from gabos_mcp.utils.db import sanitize_fts_query


def _flatten(data: dict[str, dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
	"""Flatten a folder's ``{group_type: {object_key: attrs}}`` into ``group_type/object_key`` keys.

	Returns:
	    A flat dict keyed by "group_type/object_key".
	"""
	flat: dict[str, dict[str, Any]] = {}
	for group_type, objects in data.items():
		for key, attrs in objects.items():
			flat[f"{group_type}/{key}"] = attrs
	return flat


def _diff_folder_data(
	old: dict[str, dict[str, dict[str, Any]]] | None,
	new: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, list[str]]:
	old_flat = _flatten(old or {})
	new_flat = _flatten(new)
	added = sorted(set(new_flat) - set(old_flat))
	removed = sorted(set(old_flat) - set(new_flat))
	changed = sorted(k for k in set(new_flat) & set(old_flat) if new_flat[k] != old_flat[k])
	return {"added": added, "changed": changed, "removed": removed}


def _diff_global_data(old: dict[str, Any] | None, new: dict[str, Any]) -> str:
	if old is None:
		return "added"
	return "changed" if old != new else "unchanged"


class SchemaStore(BaseStore):
	"""Persistent ground-truth schema store.

	Two tables: ``schema_folders`` (one row per folder alias, holding all of
	that folder's own object groups) and ``schema_globals`` (one row per
	Global Object). Both are upserted on conflict — no history, no merge.
	"""

	@staticmethod
	def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
		d = dict(row)
		d["data"] = json.loads(d["data"])
		return d

	async def migrate(self) -> None:
		"""Create tables and FTS indices if they do not exist."""
		if self._migrated:
			return
		conn = await self._connect()
		await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_folders (
                environment    TEXT NOT NULL,
                folder_alias   TEXT NOT NULL,
                folder_name    TEXT NOT NULL,
                server_version TEXT NOT NULL,
                imported_at    TEXT NOT NULL,
                data           TEXT NOT NULL,
                PRIMARY KEY (environment, folder_alias)
            )
        """)
		await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_globals (
                environment    TEXT NOT NULL,
                group_type     TEXT NOT NULL,
                object_name    TEXT NOT NULL,
                server_version TEXT NOT NULL,
                imported_at    TEXT NOT NULL,
                data           TEXT NOT NULL,
                PRIMARY KEY (environment, group_type, object_name)
            )
        """)
		await self._setup_fts5("schema_folders", unindexed_cols=["folder_alias"], indexed_cols=["folder_name", "data"])
		await self._setup_fts5("schema_globals", unindexed_cols=[], indexed_cols=["group_type", "object_name", "data"])
		await conn.commit()
		self._migrated = True

	async def get_last_seen_version(self, environment: str) -> str | None:
		"""Return the most recently imported server_version for an environment, if any."""
		conn = await self._connect()
		cursor = await conn.execute(
			"SELECT server_version FROM ("
			"  SELECT server_version, imported_at FROM schema_folders WHERE environment = ?"
			"  UNION ALL"
			"  SELECT server_version, imported_at FROM schema_globals WHERE environment = ?"
			") ORDER BY imported_at DESC LIMIT 1",
			(environment, environment),
		)
		row = await cursor.fetchone()
		return row["server_version"] if row else None

	async def upsert_folder(
		self,
		environment: str,
		folder_alias: str,
		folder_name: str,
		server_version: str,
		data: dict[str, dict[str, dict[str, Any]]],
	) -> dict[str, list[str]]:
		"""Upsert a folder's normalized snapshot.

		Returns:
		    An added/changed/removed diff against the row's previous data.
		"""
		conn = await self._connect()
		cursor = await conn.execute(
			"SELECT data FROM schema_folders WHERE environment = ? AND folder_alias = ?",
			(environment, folder_alias),
		)
		row = await cursor.fetchone()
		old_data = json.loads(row["data"]) if row else None
		now = _now()
		await conn.execute(
			"INSERT INTO schema_folders (environment, folder_alias, folder_name, server_version, imported_at, data) "
			"VALUES (?, ?, ?, ?, ?, ?) "
			"ON CONFLICT(environment, folder_alias) DO UPDATE SET "
			"folder_name = excluded.folder_name, server_version = excluded.server_version, "
			"imported_at = excluded.imported_at, data = excluded.data",
			(environment, folder_alias, folder_name, server_version, now, json.dumps(data)),
		)
		await conn.commit()
		return _diff_folder_data(old_data, data)

	async def upsert_global(
		self,
		environment: str,
		group_type: str,
		object_name: str,
		server_version: str,
		data: dict[str, Any],
	) -> str:
		"""Upsert a Global Object's normalized snapshot.

		Returns:
		    "added", "changed", or "unchanged" relative to the row's previous data.
		"""
		conn = await self._connect()
		cursor = await conn.execute(
			"SELECT data FROM schema_globals WHERE environment = ? AND group_type = ? AND object_name = ?",
			(environment, group_type, object_name),
		)
		row = await cursor.fetchone()
		old_data = json.loads(row["data"]) if row else None
		now = _now()
		await conn.execute(
			"INSERT INTO schema_globals (environment, group_type, object_name, server_version, imported_at, data) "
			"VALUES (?, ?, ?, ?, ?, ?) "
			"ON CONFLICT(environment, group_type, object_name) DO UPDATE SET "
			"server_version = excluded.server_version, imported_at = excluded.imported_at, data = excluded.data",
			(environment, group_type, object_name, server_version, now, json.dumps(data)),
		)
		await conn.commit()
		return _diff_global_data(old_data, data)

	async def get_folder(self, environment: str, folder_alias: str) -> dict[str, Any] | None:
		"""Return the current snapshot for a folder, or None if not found."""
		conn = await self._connect()
		cursor = await conn.execute(
			"SELECT * FROM schema_folders WHERE environment = ? AND folder_alias = ?",
			(environment, folder_alias),
		)
		row = await cursor.fetchone()
		return self._row_to_dict(row) if row else None

	async def get_global(
		self,
		environment: str,
		group_type: str,
		object_name: str | None = None,
	) -> dict[str, Any] | list[dict[str, Any]] | None:
		"""Return one Global Object (if object_name given) or all objects in a group_type."""
		conn = await self._connect()
		if object_name is not None:
			cursor = await conn.execute(
				"SELECT * FROM schema_globals WHERE environment = ? AND group_type = ? AND object_name = ?",
				(environment, group_type, object_name),
			)
			row = await cursor.fetchone()
			return self._row_to_dict(row) if row else None

		cursor = await conn.execute(
			"SELECT * FROM schema_globals WHERE environment = ? AND group_type = ? ORDER BY object_name",
			(environment, group_type),
		)
		rows = await cursor.fetchall()
		return [self._row_to_dict(r) for r in rows]

	async def diff_env(self, folder_alias: str, environment_a: str, environment_b: str) -> dict[str, Any]:
		"""Compare two environments' current live snapshots for the same folder.

		Returns:
		    A dict with found_in_a/found_in_b flags and an added/changed/removed diff.
		"""
		a = await self.get_folder(environment_a, folder_alias)
		b = await self.get_folder(environment_b, folder_alias)
		diff = _diff_folder_data(a["data"] if a else None, b["data"] if b else {})
		return {
			"folder_alias": folder_alias,
			"environment_a": environment_a,
			"environment_b": environment_b,
			"found_in_a": a is not None,
			"found_in_b": b is not None,
			**diff,
		}

	async def search(
		self,
		query: str,
		environment: str | None = None,
		limit: int = 20,
		offset: int = 0,
	) -> list[dict[str, Any]]:
		"""Full-text search over folders and Global Objects, ranked by relevance.

		Returns:
		    Matching rows (folders and/or globals) ordered by FTS5 rank, best first.
		"""
		conn = await self._connect()
		fts_query = sanitize_fts_query(query)

		folder_env_clause = "AND f.environment = ? " if environment else ""
		global_env_clause = "AND g.environment = ? " if environment else ""
		env_params = [environment] if environment else []
		params: list[Any] = [fts_query, *env_params, fts_query, *env_params, limit, offset]

		cursor = await conn.execute(
			"SELECT 'folder' AS kind, f.environment AS environment, f.folder_alias AS key1, "
			"NULL AS key2, schema_folders_fts.rank AS score "
			"FROM schema_folders_fts JOIN schema_folders f ON schema_folders_fts.rowid = f.rowid "
			"WHERE schema_folders_fts MATCH ? " + folder_env_clause + "UNION ALL "
			"SELECT 'global' AS kind, g.environment AS environment, g.group_type AS key1, "
			"g.object_name AS key2, schema_globals_fts.rank AS score "
			"FROM schema_globals_fts JOIN schema_globals g ON schema_globals_fts.rowid = g.rowid "
			"WHERE schema_globals_fts MATCH ? " + global_env_clause + "ORDER BY score LIMIT ? OFFSET ?",
			params,
		)
		rows = await cursor.fetchall()
		return [dict(r) for r in rows]
