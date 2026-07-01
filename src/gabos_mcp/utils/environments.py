"""Environment-name allowlist for schema imports (typo protection)."""

from __future__ import annotations

import os


class UnknownEnvironmentError(Exception):
	"""Raised when schema_write is called with an environment name outside the configured allowlist."""

	def __init__(self, environment: str, known_environments: list[str]) -> None:
		"""Store the rejected environment name and the currently configured allowlist."""
		self.environment = environment
		self.known_environments = known_environments
		super().__init__(f"Unknown environment {environment!r}. Configured environments: {known_environments}.")


def known_environments() -> set[str]:
	"""Return the configured allowlist of environment names, or empty if unrestricted."""
	raw = os.environ.get("GABOS_SCHEMA_ENVIRONMENTS", "")
	return {e.strip() for e in raw.split(",") if e.strip()}


def validate_environment(environment: str) -> None:
	"""Reject a blank environment name, or one outside the configured allowlist.

	If GABOS_SCHEMA_ENVIRONMENTS is unset/empty, any non-blank name is accepted
	(no allowlist configured means no restriction beyond "not blank").

	Raises:
	    UnknownEnvironmentError: If environment is blank, or a non-empty
	        allowlist is configured and environment isn't in it.
	"""
	known = known_environments()
	if not environment.strip() or (known and environment not in known):
		raise UnknownEnvironmentError(environment, sorted(known))
