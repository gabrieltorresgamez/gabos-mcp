"""Shared store factory functions to avoid duplicating path-resolution logic."""

from __future__ import annotations

import functools
import os

from platformdirs import user_data_path

from gabos_mcp.extractors.agent_store import AgentStore
from gabos_mcp.extractors.knowledge import KnowledgeStore
from gabos_mcp.extractors.schema import SchemaStore


@functools.cache
def get_knowledge_store() -> KnowledgeStore:
	"""Return the shared KnowledgeStore instance (created once, reused on subsequent calls)."""
	db_path = os.environ.get(
		"GABOS_KNOWLEDGE_DB",
		str(user_data_path("gabos-mcp") / "knowledge.db"),
	)
	return KnowledgeStore(db_path=db_path)


@functools.cache
def get_agent_store() -> AgentStore:
	"""Return the shared AgentStore instance (created once, reused on subsequent calls)."""
	db_path = os.environ.get(
		"GABOS_AGENTS_DB",
		str(user_data_path("gabos-mcp") / "agents.db"),
	)
	return AgentStore(db_path=db_path)


@functools.cache
def get_schema_store() -> SchemaStore:
	"""Return the shared SchemaStore instance (created once, reused on subsequent calls)."""
	db_path = os.environ.get(
		"GABOS_SCHEMA_DB",
		str(user_data_path("gabos-mcp") / "schema.db"),
	)
	return SchemaStore(db_path=db_path)
