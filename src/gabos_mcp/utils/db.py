"""Shared database utilities."""

from __future__ import annotations

import re
from datetime import UTC, datetime


def now() -> str:
	"""Return the current UTC time as an ISO-8601 string."""
	return datetime.now(UTC).isoformat()


def sanitize_fts_query(query: str) -> str:
	"""Strip FTS5 special characters from a user-supplied search query.

	Returns:
	    A query string safe to pass to an FTS5 MATCH clause.
	"""
	return re.sub(r"[^\w\s]", " ", query).strip() or '""'
