"""SQLite-backed store for agent definitions and CHM doc references."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite


def _now() -> str:
	return datetime.now(UTC).isoformat()


@dataclass
class Agent:
	"""An agent definition."""

	id: str
	name: str
	owner: str
	description: str
	system_prompt: str
	model: str
	knowledge_tags: list[str]
	auto_learn: bool
	shared: bool
	created_at: str
	updated_at: str

	def to_dict(self) -> dict:
		"""Serialize to a plain dict (knowledge_tags as list, auto_learn as bool)."""
		return {
			"id": self.id,
			"name": self.name,
			"owner": self.owner,
			"description": self.description,
			"system_prompt": self.system_prompt,
			"model": self.model,
			"knowledge_tags": self.knowledge_tags,
			"auto_learn": self.auto_learn,
			"shared": self.shared,
			"created_at": self.created_at,
			"updated_at": self.updated_at,
		}


@dataclass
class DocRef:
	"""A CHM page linked to an agent + context key."""

	id: str
	agent_id: str
	context_key: str
	app: str
	source: str
	page_path: str
	relevance_note: str | None
	created_by: str
	created_at: str

	def to_dict(self) -> dict:
		"""Serialize to a plain dict."""
		return {
			"id": self.id,
			"agent_id": self.agent_id,
			"context_key": self.context_key,
			"app": self.app,
			"source": self.source,
			"page_path": self.page_path,
			"relevance_note": self.relevance_note,
			"created_by": self.created_by,
			"created_at": self.created_at,
		}


class AgentStore:
	"""Persistent store for agent definitions and CHM doc references."""

	DEFAULT_MODEL = "claude-haiku-4-5-20251001"

	def __init__(self, db_path: str) -> None:
		"""Initialize with the path to the SQLite database file (created if absent)."""
		self._db_path = Path(db_path).expanduser()
		self._db_path.parent.mkdir(parents=True, exist_ok=True)
		self._conn: aiosqlite.Connection | None = None

	async def _connect(self) -> aiosqlite.Connection:
		if self._conn is None:
			self._conn = await aiosqlite.connect(str(self._db_path))
			self._conn.row_factory = aiosqlite.Row
		return self._conn

	async def _column_exists(self, table: str, column: str) -> bool:
		conn = await self._connect()
		cursor = await conn.execute(f"SELECT COUNT(*) FROM pragma_table_info('{table}') WHERE name = ?", (column,))
		row = await cursor.fetchone()
		return bool(row and row[0] > 0)

	async def migrate(self) -> None:
		"""Create tables if they do not exist, and apply incremental schema changes."""
		conn = await self._connect()
		await conn.execute("""
			CREATE TABLE IF NOT EXISTS agents (
				id            TEXT PRIMARY KEY,
				name          TEXT NOT NULL UNIQUE,
				owner         TEXT NOT NULL DEFAULT 'unknown',
				description   TEXT NOT NULL,
				system_prompt TEXT NOT NULL,
				model         TEXT NOT NULL,
				knowledge_tags TEXT NOT NULL DEFAULT '[]',
				auto_learn    INTEGER NOT NULL DEFAULT 1,
				shared        INTEGER NOT NULL DEFAULT 0,
				created_at    TEXT NOT NULL,
				updated_at    TEXT NOT NULL
			)
		""")
		if not await self._column_exists("agents", "owner"):
			await conn.execute("ALTER TABLE agents ADD COLUMN owner TEXT NOT NULL DEFAULT 'unknown'")
		if not await self._column_exists("agents", "shared"):
			await conn.execute("ALTER TABLE agents ADD COLUMN shared INTEGER NOT NULL DEFAULT 0")
		await conn.execute("""
			CREATE TABLE IF NOT EXISTS agent_doc_refs (
				id             TEXT PRIMARY KEY,
				agent_id       TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
				context_key    TEXT NOT NULL,
				app            TEXT NOT NULL,
				source         TEXT NOT NULL,
				page_path      TEXT NOT NULL,
				relevance_note TEXT,
				created_by     TEXT NOT NULL DEFAULT 'unknown',
				created_at     TEXT NOT NULL,
				UNIQUE(agent_id, context_key, app, source, page_path)
			)
		""")
		if not await self._column_exists("agent_doc_refs", "created_by"):
			await conn.execute("ALTER TABLE agent_doc_refs ADD COLUMN created_by TEXT NOT NULL DEFAULT 'unknown'")
		await conn.commit()

	@staticmethod
	def _row_to_agent(row: aiosqlite.Row) -> Agent:
		d = dict(row)
		return Agent(
			id=str(d["id"]),
			name=str(d["name"]),
			owner=str(d.get("owner") or "unknown"),
			description=str(d["description"]),
			system_prompt=str(d["system_prompt"]),
			model=str(d["model"]),
			knowledge_tags=json.loads(str(d["knowledge_tags"])),
			auto_learn=bool(d["auto_learn"]),
			shared=bool(d.get("shared", 0)),
			created_at=str(d["created_at"]),
			updated_at=str(d["updated_at"]),
		)

	@staticmethod
	def _row_to_doc_ref(row: aiosqlite.Row) -> DocRef:
		d = dict(row)
		raw_note = d.get("relevance_note")
		return DocRef(
			id=str(d["id"]),
			agent_id=str(d["agent_id"]),
			context_key=str(d["context_key"]),
			app=str(d["app"]),
			source=str(d["source"]),
			page_path=str(d["page_path"]),
			relevance_note=str(raw_note) if raw_note is not None else None,
			created_by=str(d.get("created_by") or "unknown"),
			created_at=str(d["created_at"]),
		)

	# ── Agent CRUD ─────────────────────────────────────────────────────────────

	async def create(
		self,
		owner: str,
		name: str,
		description: str,
		system_prompt: str,
		model: str | None = None,
		knowledge_tags: list[str] | None = None,
		auto_learn: bool = True,
		shared: bool = False,
	) -> Agent:
		"""Create a new agent definition.

		Args:
		    owner: GitHub login of the creator.
		    name: Unique slug (e.g. "omnitracker").
		    description: One-line description shown in agent_list.
		    system_prompt: Full persona and instructions for the agent.
		    model: Claude model ID. Defaults to claude-haiku-4-5-20251001.
		    knowledge_tags: Tags used to filter knowledge entries into context.
		    auto_learn: Whether to run the learning loop after each ask.
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
				"INSERT INTO agents (id, name, owner, description, system_prompt, model, "
				"knowledge_tags, auto_learn, shared, created_at, updated_at) "
				"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
				(
					agent_id,
					name,
					owner,
					description,
					system_prompt,
					model or self.DEFAULT_MODEL,
					json.dumps(knowledge_tags or []),
					1 if auto_learn else 0,
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
			model=model or self.DEFAULT_MODEL,
			knowledge_tags=knowledge_tags or [],
			auto_learn=auto_learn,
			shared=shared,
			created_at=now,
			updated_at=now,
		)

	async def get(self, name_or_id: str) -> Agent | None:
		"""Return an agent by name or ID, or None if not found."""
		conn = await self._connect()
		cursor = await conn.execute(
			"SELECT * FROM agents WHERE name = ? OR id = ?",
			(name_or_id, name_or_id),
		)
		row = await cursor.fetchone()
		return self._row_to_agent(row) if row else None

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
		name_or_id: str,
		owner: str,
		description: str | None = None,
		system_prompt: str | None = None,
		model: str | None = None,
		knowledge_tags: list[str] | None = None,
		auto_learn: bool | None = None,
		shared: bool | None = None,
	) -> Agent:
		"""Update an agent definition (partial update). Only the owner may update.

		Args:
		    name_or_id: Agent name or UUID.
		    owner: GitHub login of the caller (must match the agent's owner).
		    description: New description, or None to keep existing.
		    system_prompt: New system prompt, or None to keep existing.
		    model: New model ID, or None to keep existing.
		    knowledge_tags: New tag list, or None to keep existing.
		    auto_learn: New auto_learn flag, or None to keep existing.
		    shared: New shared flag, or None to keep existing.

		Returns:
		    The updated Agent.

		Raises:
		    KeyError: If the agent does not exist.
		    PermissionError: If the caller is not the owner.
		"""
		agent = await self.get(name_or_id)
		if agent is None:
			raise KeyError(f"Agent '{name_or_id}' not found.")
		if agent.owner != owner:
			raise PermissionError("You can only edit your own agents.")

		new_description = description if description is not None else agent.description
		new_system_prompt = system_prompt if system_prompt is not None else agent.system_prompt
		new_model = model if model is not None else agent.model
		new_tags = knowledge_tags if knowledge_tags is not None else agent.knowledge_tags
		new_auto_learn = auto_learn if auto_learn is not None else agent.auto_learn
		new_shared = shared if shared is not None else agent.shared
		now = _now()

		conn = await self._connect()
		await conn.execute(
			"UPDATE agents SET description = ?, system_prompt = ?, model = ?, "
			"knowledge_tags = ?, auto_learn = ?, shared = ?, updated_at = ? WHERE id = ?",
			(
				new_description,
				new_system_prompt,
				new_model,
				json.dumps(new_tags),
				1 if new_auto_learn else 0,
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
			model=new_model,
			knowledge_tags=new_tags,
			auto_learn=new_auto_learn,
			shared=new_shared,
			created_at=agent.created_at,
			updated_at=now,
		)

	async def delete(self, name_or_id: str, owner: str) -> None:
		"""Delete an agent and all its doc refs (cascade). Only the owner may delete.

		Args:
		    name_or_id: Agent name or UUID.
		    owner: GitHub login of the caller (must match the agent's owner).

		Raises:
		    KeyError: If the agent does not exist.
		    PermissionError: If the caller is not the owner.
		"""
		agent = await self.get(name_or_id)
		if agent is None:
			raise KeyError(f"Agent '{name_or_id}' not found.")
		if agent.owner != owner:
			raise PermissionError("You can only delete your own agents.")
		conn = await self._connect()
		await conn.execute("DELETE FROM agents WHERE id = ?", (agent.id,))
		await conn.commit()

	# ── Doc Ref CRUD ───────────────────────────────────────────────────────────

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

	async def add_doc_ref(
		self,
		agent_name_or_id: str,
		context_key: str,
		app: str,
		source: str,
		page_path: str,
		relevance_note: str | None = None,
		caller: str | None = None,
	) -> DocRef:
		"""Link a CHM page to an agent + context key. Only the agent owner may add refs.

		Args:
		    agent_name_or_id: Agent name or UUID.
		    context_key: Folder name (e.g. "Tickets") or "_global".
		    app: CHM app name (e.g. "OMNITRACKER").
		    source: CHM source name.
		    page_path: Page path within the CHM source.
		    relevance_note: Optional note on why this page is relevant.
		    caller: GitHub login of the caller. Must match the agent's owner.

		Returns:
		    The created DocRef.

		Raises:
		    KeyError: If the agent does not exist.
		    PermissionError: If caller is not the agent owner.
		    ValueError: If the same ref already exists.
		"""
		agent = await self.get(agent_name_or_id)
		if agent is None:
			raise KeyError(f"Agent '{agent_name_or_id}' not found.")
		if caller is not None and agent.owner != caller:
			raise PermissionError("You can only add doc refs to your own agents.")

		now = _now()
		ref_id = str(uuid.uuid4())
		created_by = caller or "unknown"
		conn = await self._connect()
		try:
			await conn.execute(
				"INSERT INTO agent_doc_refs "
				"(id, agent_id, context_key, app, source, page_path, relevance_note, created_by, created_at) "
				"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
				(ref_id, agent.id, context_key, app, source, page_path, relevance_note, created_by, now),
			)
		except aiosqlite.IntegrityError as e:
			raise ValueError(
				f"Doc ref for '{app}/{source}/{page_path}' in context '{context_key}' already exists."
			) from e
		await conn.commit()
		return DocRef(
			id=ref_id,
			agent_id=agent.id,
			context_key=context_key,
			app=app,
			source=source,
			page_path=page_path,
			relevance_note=relevance_note,
			created_by=created_by,
			created_at=now,
		)

	async def list_doc_refs(
		self,
		agent_name_or_id: str,
		context_keys: list[str] | None = None,
	) -> list[DocRef]:
		"""Return doc refs for an agent, optionally filtered to specific context keys.

		Args:
		    agent_name_or_id: Agent name or UUID.
		    context_keys: If provided, only return refs matching these keys.

		Returns:
		    List of DocRef ordered by context_key, page_path.

		Raises:
		    KeyError: If the agent does not exist.
		"""
		agent = await self.get(agent_name_or_id)
		if agent is None:
			raise KeyError(f"Agent '{agent_name_or_id}' not found.")

		conn = await self._connect()
		if context_keys:
			placeholders = ",".join("?" * len(context_keys))
			cursor = await conn.execute(
				f"SELECT * FROM agent_doc_refs WHERE agent_id = ? "
				f"AND context_key IN ({placeholders}) "
				"ORDER BY context_key, page_path",
				(agent.id, *context_keys),
			)
		else:
			cursor = await conn.execute(
				"SELECT * FROM agent_doc_refs WHERE agent_id = ? ORDER BY context_key, page_path",
				(agent.id,),
			)
		rows = await cursor.fetchall()
		return [self._row_to_doc_ref(r) for r in rows]

	async def delete_doc_ref(self, ref_id: str, caller: str | None = None) -> None:
		"""Delete a doc ref by ID. Only the agent owner may delete refs.

		Args:
		    ref_id: The UUID of the doc ref.
		    caller: GitHub login of the calling user.

		Raises:
		    KeyError: If the ref does not exist.
		    PermissionError: If caller is not the agent owner.
		"""
		conn = await self._connect()
		cursor = await conn.execute(
			"SELECT dr.id, a.owner FROM agent_doc_refs dr JOIN agents a ON dr.agent_id = a.id WHERE dr.id = ?",
			(ref_id,),
		)
		row = await cursor.fetchone()
		if row is None:
			raise KeyError(f"Doc ref '{ref_id}' not found.")
		if caller is not None and caller != str(row["owner"]):
			raise PermissionError("You can only delete doc refs from your own agents.")
		await conn.execute("DELETE FROM agent_doc_refs WHERE id = ?", (ref_id,))
		await conn.commit()

	async def close(self) -> None:
		"""Close the database connection and release the background thread."""
		if self._conn is not None:
			await self._conn.close()
			self._conn = None
