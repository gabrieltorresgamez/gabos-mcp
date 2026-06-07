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

	async def close(self) -> None:
		"""Close the database connection and release the background thread."""
		if self._conn is not None:
			await self._conn.close()
			self._conn = None
