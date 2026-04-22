"""Shared store factory functions to avoid duplicating path-resolution logic."""

from __future__ import annotations

import os

from platformdirs import user_data_path

from gabos_mcp.extractors.agent_store import AgentStore
from gabos_mcp.extractors.knowledge import KnowledgeStore


def get_knowledge_store() -> KnowledgeStore:
	"""Return a KnowledgeStore using the configured or default DB path."""
	db_path = os.environ.get(
		"GABOS_KNOWLEDGE_DB",
		str(user_data_path("gabos-mcp") / "knowledge.db"),
	)
	return KnowledgeStore(db_path=db_path)


def get_agent_store() -> AgentStore:
	"""Return an AgentStore using the configured or default DB path."""
	db_path = os.environ.get(
		"GABOS_AGENTS_DB",
		str(user_data_path("gabos-mcp") / "agents.db"),
	)
	return AgentStore(db_path=db_path)
