"""Shared store factory functions to avoid duplicating path-resolution logic."""

from __future__ import annotations

import functools
import os

from platformdirs import user_data_path

from gabos_mcp.extractors.agent_store import AgentStore
from gabos_mcp.extractors.knowledge import KnowledgeStore
from gabos_mcp.extractors.schema import SchemaStore

# name -> (env var, default filename). Single source of truth for every
# registered database, so backup rotation doesn't need its own copy.
_DB_SPECS: dict[str, tuple[str, str]] = {
	"agents": ("GABOS_AGENTS_DB", "agents.db"),
	"knowledge": ("GABOS_KNOWLEDGE_DB", "knowledge.db"),
	"schema": ("GABOS_SCHEMA_DB", "schema.db"),
}


def registered_db_names() -> list[str]:
	"""Return the names of all registered databases, e.g. for backup rotation."""
	return list(_DB_SPECS)


def db_path(name: str) -> str:
	"""Return the configured or default filesystem path for a registered database."""
	env_var, default_name = _DB_SPECS[name]
	return os.environ.get(env_var, str(user_data_path("gabos-mcp") / default_name))


@functools.cache
def get_knowledge_store() -> KnowledgeStore:
	"""Return the shared KnowledgeStore instance (created once, reused on subsequent calls)."""
	return KnowledgeStore(db_path=db_path("knowledge"))


@functools.cache
def get_agent_store() -> AgentStore:
	"""Return the shared AgentStore instance (created once, reused on subsequent calls)."""
	return AgentStore(db_path=db_path("agents"))


@functools.cache
def get_schema_store() -> SchemaStore:
	"""Return the shared SchemaStore instance (created once, reused on subsequent calls)."""
	return SchemaStore(db_path=db_path("schema"))
