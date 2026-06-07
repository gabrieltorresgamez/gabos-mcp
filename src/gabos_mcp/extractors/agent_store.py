"""SQLite-backed store for agent definitions."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import aiosqlite

from gabos_mcp.extractors.base import BaseStore
from gabos_mcp.utils.db import now as _now


@dataclass
class Agent:
	"""An agent definition."""

	id: str
	name: str
	owner: str
	description: str
	system_prompt: str
	knowledge_tags: list[str]
	shared: bool
	created_at: str
	updated_at: str

	def to_dict(self) -> dict:
		"""Serialize to a plain dict.

		Returns:
		    Plain dict representation of this agent.
		"""
		return {
			"id": self.id,
			"name": self.name,
			"owner": self.owner,
			"description": self.description,
			"system_prompt": self.system_prompt,
			"knowledge_tags": self.knowledge_tags,
			"shared": self.shared,
			"created_at": self.created_at,
			"updated_at": self.updated_at,
		}


class AgentStore(BaseStore):
	"""Persistent store for agent definitions."""

	async def migrate(self) -> None:
		"""Create tables if they do not exist, and apply incremental schema changes."""
		if self._migrated:
			return
		conn = await self._connect()
		await conn.execute("""
			CREATE TABLE IF NOT EXISTS agents (
				id            TEXT PRIMARY KEY,
				name          TEXT NOT NULL UNIQUE,
				owner         TEXT NOT NULL DEFAULT 'unknown',
				description   TEXT NOT NULL,
				system_prompt TEXT NOT NULL,
				knowledge_tags TEXT NOT NULL DEFAULT '[]',
				shared        INTEGER NOT NULL DEFAULT 0,
				created_at    TEXT NOT NULL,
				updated_at    TEXT NOT NULL
			)
		""")
		if not await self._column_exists("agents", "owner"):
			await conn.execute("ALTER TABLE agents ADD COLUMN owner TEXT NOT NULL DEFAULT 'unknown'")
		if not await self._column_exists("agents", "shared"):
			await conn.execute("ALTER TABLE agents ADD COLUMN shared INTEGER NOT NULL DEFAULT 0")
		if await self._column_exists("agents", "model"):
			await conn.execute("ALTER TABLE agents DROP COLUMN model")
		await conn.commit()
		self._migrated = True

	@staticmethod
	def _row_to_agent(row: aiosqlite.Row) -> Agent:
		d = dict(row)
		return Agent(
			id=str(d["id"]),
			name=str(d["name"]),
			owner=str(d.get("owner") or "unknown"),
			description=str(d["description"]),
			system_prompt=str(d["system_prompt"]),
			knowledge_tags=json.loads(str(d["knowledge_tags"])),
			shared=bool(d.get("shared")),
			created_at=str(d["created_at"]),
			updated_at=str(d["updated_at"]),
		)

	# ── Agent CRUD ─────────────────────────────────────────────────────────────

	async def create(
		self,
		owner: str,
		name: str,
		description: str,
		system_prompt: str,
		knowledge_tags: list[str] | None = None,
		shared: bool = False,
	) -> Agent:
		"""Create a new agent definition.

		Args:
		    owner: GitHub login of the creator.
		    name: Unique slug (e.g. "omnitracker").
		    description: One-line description shown in agent_list.
		    system_prompt: Full persona and instructions for the agent.
		    knowledge_tags: Tags to search when retrieving this agent's knowledge.
		    shared: Whether the agent is visible to all authenticated users.

		Returns:
		    The created Agent.

		Raises:
		    ValueError: If an agent with the same name already exists.
		"""
		now = _now()
		agent_id = str(uuid.uuid4())
		conn = await self._connect()
		try:
			await conn.execute(
				"INSERT INTO agents (id, name, owner, description, system_prompt, "
				"knowledge_tags, shared, created_at, updated_at) "
				"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
				(
					agent_id,
					name,
					owner,
					description,
					system_prompt,
					json.dumps(knowledge_tags or []),
					1 if shared else 0,
					now,
					now,
				),
			)
		except aiosqlite.IntegrityError as e:
			raise ValueError(f"Agent '{name}' already exists.") from e
		await conn.commit()
		return Agent(
			id=agent_id,
			name=name,
			owner=owner,
			description=description,
			system_prompt=system_prompt,
			knowledge_tags=knowledge_tags or [],
			shared=shared,
			created_at=now,
			updated_at=now,
		)

	async def get_by_id(self, id: str, caller: str | None = None) -> Agent | None:
		"""Return an agent by UUID, or None if not found.

		Args:
		    id: Agent UUID.
		    caller: If provided, raises PermissionError when the agent exists but
		            is private and not owned by this caller.

		Raises:
		    PermissionError: If the agent exists but is not visible to caller.
		"""
		conn = await self._connect()
		cursor = await conn.execute("SELECT * FROM agents WHERE id = ?", (id,))
		row = await cursor.fetchone()
		if row is None:
			return None
		agent = self._row_to_agent(row)
		if caller is not None and agent.owner != caller and not agent.shared:
			raise PermissionError(f"Agent '{id}' not found or access denied.")
		return agent

	async def list_agents(self, caller: str | None = None) -> list[Agent]:
		"""Return agents visible to the caller, ordered by name.

		Args:
		    caller: GitHub login of the calling user. When provided, returns only
		            agents owned by the caller or marked as shared. When None,
		            returns all agents (for internal use).
		"""
		conn = await self._connect()
		if caller is not None:
			cursor = await conn.execute(
				"SELECT * FROM agents WHERE owner = ? OR shared = 1 ORDER BY name",
				(caller,),
			)
		else:
			cursor = await conn.execute("SELECT * FROM agents ORDER BY name")
		rows = await cursor.fetchall()
		return [self._row_to_agent(r) for r in rows]

	async def update(
		self,
		id: str,
		owner: str,
		description: str | None = None,
		system_prompt: str | None = None,
		knowledge_tags: list[str] | None = None,
		shared: bool | None = None,
	) -> Agent:
		"""Update an agent definition (partial update). Only the owner may update.

		Args:
		    id: Agent UUID.
		    owner: GitHub login of the caller (must match the agent's owner).
		    description: New description, or None to keep existing.
		    system_prompt: New system prompt, or None to keep existing.
		    knowledge_tags: New tag list, or None to keep existing.
		    shared: New shared flag, or None to keep existing.

		Returns:
		    The updated Agent.

		Raises:
		    KeyError: If the agent does not exist.
		    PermissionError: If the caller is not the owner.
		"""
		agent = await self.get_by_id(id)
		if agent is None:
			raise KeyError(f"Agent '{id}' not found.")
		if agent.owner != owner:
			raise PermissionError("You can only edit your own agents.")

		new_description = description if description is not None else agent.description
		new_system_prompt = system_prompt if system_prompt is not None else agent.system_prompt
		new_tags = knowledge_tags if knowledge_tags is not None else agent.knowledge_tags
		new_shared = shared if shared is not None else agent.shared
		now = _now()

		conn = await self._connect()
		await conn.execute(
			"UPDATE agents SET description = ?, system_prompt = ?, "
			"knowledge_tags = ?, shared = ?, updated_at = ? WHERE id = ?",
			(
				new_description,
				new_system_prompt,
				json.dumps(new_tags),
				1 if new_shared else 0,
				now,
				agent.id,
			),
		)
		await conn.commit()
		return Agent(
			id=agent.id,
			name=agent.name,
			owner=agent.owner,
			description=new_description,
			system_prompt=new_system_prompt,
			knowledge_tags=new_tags,
			shared=new_shared,
			created_at=agent.created_at,
			updated_at=now,
		)

	async def delete(self, id: str, owner: str) -> None:
		"""Delete an agent (cascade to doc refs). Only the owner may delete.

		Args:
		    id: Agent UUID.
		    owner: GitHub login of the caller (must match the agent's owner).

		Raises:
		    KeyError: If the agent does not exist.
		    PermissionError: If the caller is not the owner.
		"""
		agent = await self.get_by_id(id)
		if agent is None:
			raise KeyError(f"Agent '{id}' not found.")
		if agent.owner != owner:
			raise PermissionError("You can only delete your own agents.")
		conn = await self._connect()
		await conn.execute("DELETE FROM agents WHERE id = ?", (agent.id,))
		await conn.commit()

	async def get_many(self, names: list[str]) -> dict[str, Agent]:
		"""Return agents by name in a single query, keyed by name."""
		if not names:
			return {}
		conn = await self._connect()
		placeholders = ",".join("?" * len(names))
		cursor = await conn.execute(
			f"SELECT * FROM agents WHERE name IN ({placeholders})",
			names,
		)
		rows = await cursor.fetchall()
		return {r["name"]: self._row_to_agent(r) for r in rows}
