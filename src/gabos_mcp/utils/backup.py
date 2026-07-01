"""Daily SQLite backup scheduler."""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path

from gabos_mcp.utils.stores import db_path, registered_db_names

logger = logging.getLogger(__name__)


def backup_database(source_path: str, dest_path: str) -> None:
	"""Copy source SQLite DB to dest using the Online Backup API."""
	src = sqlite3.connect(source_path)
	dst = sqlite3.connect(dest_path)
	with dst:
		src.backup(dst)
	dst.close()
	src.close()


def _seconds_until(target: time) -> float:
	now = datetime.now()  # noqa: DTZ005
	run_at = datetime.combine(now.date(), target)
	if run_at <= now:
		run_at += timedelta(days=1)
	return (run_at - now).total_seconds()


def _parse_backup_time() -> time:
	raw = os.environ.get("GABOS_BACKUP_TIME", "02:00")
	try:
		h, m = raw.split(":")
		return time(int(h), int(m))
	except ValueError, AttributeError:
		logger.exception("Invalid GABOS_BACKUP_TIME %r, defaulting to 02:00", raw)
		return time(2, 0)


def _retention_days() -> int:
	return int(os.environ.get("GABOS_BACKUP_RETENTION_DAYS", "30"))


def _cleanup_old_backups(backup_dir: Path) -> None:
	retention = _retention_days()
	if retention == 0:
		return
	cutoff = date.today() - timedelta(days=retention)  # noqa: DTZ011
	for name in registered_db_names():
		for f in backup_dir.glob(f"{name}_*.db"):
			try:
				date_part = f.stem.split("_", 1)[1]
				file_date = datetime.strptime(date_part, "%Y-%m-%d").date()  # noqa: DTZ007
			except IndexError, ValueError:
				continue
			if file_date < cutoff:
				f.unlink()
				logger.info("Deleted expired backup: %s", f)


async def run_backup(backup_dir: Path) -> bool:
	"""Back up both databases into backup_dir.

	Returns:
	    True if all database backups succeeded, False if any failed.
	"""
	today = date.today().strftime("%Y-%m-%d")  # noqa: DTZ011
	all_ok = True
	for name in registered_db_names():
		source = db_path(name)
		dest = backup_dir / f"{name}_{today}.db"
		if dest.exists():
			logger.info("Today's backup already exists, skipping: %s", dest)
			continue
		if not Path(source).exists():
			logger.warning("Database not found, skipping backup: %s", source)
			continue
		try:
			await asyncio.to_thread(backup_database, source, str(dest))
			logger.info("Backup created: %s", dest)
		except Exception:
			logger.exception("Backup failed for %s", source)
			dest.unlink(missing_ok=True)
			all_ok = False
	return all_ok


async def backup_scheduler() -> None:
	"""Long-running background task: backs up both DBs daily at GABOS_BACKUP_TIME."""
	backup_dir_str = os.environ.get("GABOS_BACKUP_DIR")
	if not backup_dir_str:
		return

	backup_dir = Path(backup_dir_str)
	try:
		backup_dir.mkdir(parents=True, exist_ok=True)
		probe = backup_dir / ".write_probe"
		probe.touch()
		probe.unlink()
	except OSError:
		logger.exception("GABOS_BACKUP_DIR is not writable — backups disabled")
		return

	backup_time = _parse_backup_time()
	logger.info("Backup scheduler active: %s at %s, retention %d days", backup_dir, backup_time, _retention_days())

	# Run immediately on startup if today's backup is missing for any registered DB.
	today = date.today().strftime("%Y-%m-%d")  # noqa: DTZ011
	missing = any(not (backup_dir / f"{name}_{today}.db").exists() for name in registered_db_names())
	if missing:
		ok = await run_backup(backup_dir)
		if ok:
			_cleanup_old_backups(backup_dir)

	while True:
		await asyncio.sleep(_seconds_until(backup_time))
		ok = await run_backup(backup_dir)
		if ok:
			_cleanup_old_backups(backup_dir)
