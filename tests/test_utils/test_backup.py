"""Tests for the daily backup scheduler utilities."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from gabos_mcp.utils.backup import (
	_cleanup_old_backups,
	_seconds_until,
	backup_database,
	run_backup,
)

# ── backup_database ─────────────────────────────────────────────────────────


def test_backup_database_creates_valid_copy(tmp_path):
	src = tmp_path / "source.db"
	dst = tmp_path / "dest.db"
	conn = sqlite3.connect(str(src))
	conn.execute("CREATE TABLE t (v TEXT)")
	conn.execute("INSERT INTO t VALUES ('hello')")
	conn.commit()
	conn.close()

	backup_database(str(src), str(dst))

	assert dst.exists()
	c = sqlite3.connect(str(dst))
	rows = c.execute("SELECT v FROM t").fetchall()
	c.close()
	assert rows == [("hello",)]


# ── _seconds_until ───────────────────────────────────────────────────────────


def test_seconds_until_future_time():
	future = (datetime.now() + timedelta(hours=1)).time()
	secs = _seconds_until(future)
	assert 3500 < secs <= 3600


def test_seconds_until_past_time_wraps_to_tomorrow():
	past = (datetime.now() - timedelta(hours=1)).time()
	secs = _seconds_until(past)
	assert 82700 < secs <= 86400  # ~23 h


# ── _cleanup_old_backups ──────────────────────────────────────────────────────


def test_cleanup_removes_expired_files(tmp_path):
	old_date = (date.today() - timedelta(days=35)).strftime("%Y-%m-%d")
	recent_date = date.today().strftime("%Y-%m-%d")

	old_agents = tmp_path / f"agents_{old_date}.db"
	old_agents.touch()
	recent_agents = tmp_path / f"agents_{recent_date}.db"
	recent_agents.touch()

	with patch.dict("os.environ", {"GABOS_BACKUP_RETENTION_DAYS": "30"}):
		_cleanup_old_backups(tmp_path)

	assert not old_agents.exists()
	assert recent_agents.exists()


def test_cleanup_keeps_all_when_retention_zero(tmp_path):
	old_date = (date.today() - timedelta(days=365)).strftime("%Y-%m-%d")
	f = tmp_path / f"agents_{old_date}.db"
	f.touch()

	with patch.dict("os.environ", {"GABOS_BACKUP_RETENTION_DAYS": "0"}):
		_cleanup_old_backups(tmp_path)

	assert f.exists()


def test_cleanup_ignores_unrecognised_files(tmp_path):
	f = tmp_path / "random_file.db"
	f.touch()
	_cleanup_old_backups(tmp_path)
	assert f.exists()


# ── run_backup ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_backup_creates_files(tmp_path):
	agents_db = tmp_path / "agents.db"
	knowledge_db = tmp_path / "knowledge.db"
	backup_dir = tmp_path / "backups"
	backup_dir.mkdir()

	for db in (agents_db, knowledge_db):
		conn = sqlite3.connect(str(db))
		conn.execute("CREATE TABLE t (v TEXT)")
		conn.commit()
		conn.close()

	with patch.dict(
		"os.environ",
		{
			"GABOS_AGENTS_DB": str(agents_db),
			"GABOS_KNOWLEDGE_DB": str(knowledge_db),
		},
	):
		ok = await run_backup(backup_dir)

	assert ok
	today = date.today().strftime("%Y-%m-%d")
	assert (backup_dir / f"agents_{today}.db").exists()
	assert (backup_dir / f"knowledge_{today}.db").exists()


@pytest.mark.asyncio
async def test_run_backup_skips_existing(tmp_path):
	agents_db = tmp_path / "agents.db"
	backup_dir = tmp_path / "backups"
	backup_dir.mkdir()
	today = date.today().strftime("%Y-%m-%d")

	conn = sqlite3.connect(str(agents_db))
	conn.execute("CREATE TABLE t (v TEXT)")
	conn.commit()
	conn.close()

	existing = backup_dir / f"agents_{today}.db"
	existing.write_bytes(b"existing")

	knowledge_db = tmp_path / "knowledge.db"
	conn2 = sqlite3.connect(str(knowledge_db))
	conn2.execute("CREATE TABLE t (v TEXT)")
	conn2.commit()
	conn2.close()

	with patch.dict(
		"os.environ",
		{
			"GABOS_AGENTS_DB": str(agents_db),
			"GABOS_KNOWLEDGE_DB": str(knowledge_db),
		},
	):
		ok = await run_backup(backup_dir)

	assert ok
	assert existing.read_bytes() == b"existing"


@pytest.mark.asyncio
async def test_run_backup_skips_missing_db(tmp_path):
	backup_dir = tmp_path / "backups"
	backup_dir.mkdir()

	with patch.dict(
		"os.environ",
		{
			"GABOS_AGENTS_DB": str(tmp_path / "nonexistent_agents.db"),
			"GABOS_KNOWLEDGE_DB": str(tmp_path / "nonexistent_knowledge.db"),
		},
	):
		ok = await run_backup(backup_dir)

	assert ok
	assert list(backup_dir.iterdir()) == []
