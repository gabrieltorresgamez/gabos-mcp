"""Shared SQLite store base class."""

from __future__ import annotations

from pathlib import Path

import aiosqlite


class BaseStore:
	"""Common connection management for SQLite-backed stores."""

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

	async def _setup_fts5(self, table: str, unindexed_cols: list[str], indexed_cols: list[str]) -> None:
		"""Create an FTS5 external-content index + sync triggers for ``table``, if absent.

		``unindexed_cols``/``indexed_cols`` must name real columns of ``table`` — FTS5
		external-content mode (``content='<table>'``) requires the FTS column names to
		match the source table's column names exactly. The index is only rebuilt the
		first time the table is created, not on every call (e.g. every process restart).
		"""
		conn = await self._connect()
		fts_table = f"{table}_fts"
		cursor = await conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (fts_table,))
		already_exists = await cursor.fetchone() is not None
		all_cols = [*unindexed_cols, *indexed_cols]
		col_defs = ", ".join([*(f"{c} UNINDEXED" for c in unindexed_cols), *indexed_cols])
		col_list = ", ".join(all_cols)
		new_list = ", ".join(f"new.{c}" for c in all_cols)
		old_list = ", ".join(f"old.{c}" for c in all_cols)

		await conn.execute(f"""
			CREATE VIRTUAL TABLE IF NOT EXISTS {fts_table}
			USING fts5({col_defs}, tokenize='trigram', content='{table}', content_rowid='rowid')
		""")
		await conn.execute(f"""
			CREATE TRIGGER IF NOT EXISTS {table}_fts_insert
			AFTER INSERT ON {table} BEGIN
				INSERT INTO {fts_table}(rowid, {col_list}) VALUES (new.rowid, {new_list});
			END
		""")
		await conn.execute(f"""
			CREATE TRIGGER IF NOT EXISTS {table}_fts_update
			AFTER UPDATE ON {table} BEGIN
				INSERT INTO {fts_table}({fts_table}, rowid, {col_list}) VALUES ('delete', old.rowid, {old_list});
				INSERT INTO {fts_table}(rowid, {col_list}) VALUES (new.rowid, {new_list});
			END
		""")
		await conn.execute(f"""
			CREATE TRIGGER IF NOT EXISTS {table}_fts_delete
			AFTER DELETE ON {table} BEGIN
				INSERT INTO {fts_table}({fts_table}, rowid, {col_list}) VALUES ('delete', old.rowid, {old_list});
			END
		""")
		if not already_exists:
			await conn.execute(f"INSERT INTO {fts_table}({fts_table}) VALUES('rebuild')")

	async def close(self) -> None:
		"""Close the database connection and release the background thread."""
		if self._conn is not None:
			await self._conn.close()
			self._conn = None
