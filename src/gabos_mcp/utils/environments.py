"""Environment resolution for schema imports (Head server identity -> environment name)."""

from __future__ import annotations

import json
import os


class SchemaEnvironmentResolutionError(Exception):
	"""Raised when an export's Head identity can't be matched to a configured environment."""

	def __init__(self, host_key: str, known_environments: list[str]) -> None:
		"""Store the unmatched host identity and the currently configured environment names."""
		self.host_key = host_key
		self.known_environments = known_environments
		super().__init__(
			f"No configured environment matches server identity {host_key!r}. "
			f"Configured environments: {known_environments}."
		)


def _load_environment_map() -> dict[str, str]:
	raw = os.environ.get("GABOS_SCHEMA_ENVIRONMENTS", "{}")
	try:
		mapping = json.loads(raw)
	except json.JSONDecodeError:
		return {}
	return mapping if isinstance(mapping, dict) else {}


def resolve_environment(server_name: str, server_port: str, override: str | None = None) -> str:
	"""Resolve an export's Head identity to a configured environment name.

	Args:
	    server_name: Head/ServerName from the export.
	    server_port: Head/ServerPort from the export.
	    override: Explicit environment name, bypassing auto-detection.

	Returns:
	    The resolved environment name.

	Raises:
	    SchemaEnvironmentResolutionError: If no override is given and no configured
	        environment's host matches "ServerName:ServerPort".
	"""
	if override:
		return override
	mapping = _load_environment_map()
	host_key = f"{server_name}:{server_port}"
	for env_name, host in mapping.items():
		if host == host_key:
			return env_name
	raise SchemaEnvironmentResolutionError(host_key, sorted(mapping.keys()))
