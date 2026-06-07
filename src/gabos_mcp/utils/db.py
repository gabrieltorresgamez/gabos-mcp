"""Shared database utilities."""

from __future__ import annotations

from datetime import UTC, datetime


def now() -> str:
	"""Return the current UTC time as an ISO-8601 string."""
	return datetime.now(UTC).isoformat()
