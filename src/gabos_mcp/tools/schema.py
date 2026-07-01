"""MCP tools for the ground-truth schema store (OMNITRACKER Export Documentation)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from gabos_mcp.extractors.schema_xml import SchemaValidationError, parse_export
from gabos_mcp.utils.auth import get_github_login, is_schema_admin
from gabos_mcp.utils.environments import SchemaEnvironmentResolutionError, resolve_environment
from gabos_mcp.utils.stores import get_schema_store
from gabos_mcp.utils.uploads import get_schema_file_upload

if TYPE_CHECKING:
	from fastmcp import FastMCP
	from fastmcp.server.context import Context


def _require_authenticated() -> str:
	user = get_github_login()
	if user == "anonymous":
		raise PermissionError("Authentication required to read schema data.")
	return user


def register(mcp: FastMCP) -> None:  # noqa: C901
	"""Register schema tools on the given FastMCP instance."""
	store = get_schema_store()
	file_upload = get_schema_file_upload()

	@mcp.tool
	async def schema_import(file_name: str, ctx: Context, environment: str | None = None) -> str:
		"""Parse an uploaded OMNITRACKER Export Documentation XML and upsert it into the schema store.

		Upload the XML via the Schema Import file-upload UI first, then call this
		with the uploaded file's name. Admin-only (GABOS_SCHEMA_ADMINS).

		The environment is auto-detected from the export's Head/ServerName +
		Head/ServerPort against GABOS_SCHEMA_ENVIRONMENTS. Pass environment to
		override auto-detection (first-time setup, or a renamed/re-pointed host).

		Every folder and Global Object group present in the export is normalized
		and stored — nothing is filtered by type or size. Re-importing a
		folder/object overwrites its row. The raw upload is deleted after a
		successful import; nothing is retained beyond the normalized snapshot.

		Args:
		    file_name: Name of a file previously uploaded via the file-upload UI.
		    ctx: Injected request context (session scoping for the uploaded file).
		    environment: Explicit environment name, bypassing auto-detection.
		"""
		user = _require_authenticated()
		if not is_schema_admin(user):
			raise PermissionError("Only schema admins may import schema exports.")
		await store.migrate()

		raw_bytes = file_upload.get_raw_bytes(file_name, ctx)

		try:
			parsed = parse_export(raw_bytes)
		except SchemaValidationError as e:
			return json.dumps({"error": str(e)})

		try:
			resolved_env = resolve_environment(parsed.head.server_name, parsed.head.server_port, environment)
		except SchemaEnvironmentResolutionError as e:
			return json.dumps(
				{
					"error": "Could not resolve environment from Head block.",
					"server_identity": e.host_key,
					"configured_environments": e.known_environments,
				}
			)

		previous_version = await store.get_last_seen_version(resolved_env)

		folder_diffs = {}
		for folder in parsed.folders:
			folder_diffs[folder.alias] = await store.upsert_folder(
				environment=resolved_env,
				folder_alias=folder.alias,
				folder_name=folder.name,
				server_version=parsed.head.server_version,
				data=folder.data,
			)

		global_diffs = {}
		for obj in parsed.globals:
			global_diffs[f"{obj.group_type}/{obj.object_name}"] = await store.upsert_global(
				environment=resolved_env,
				group_type=obj.group_type,
				object_name=obj.object_name,
				server_version=parsed.head.server_version,
				data=obj.data,
			)

		file_upload.forget(file_name, ctx)

		result = {
			"environment": resolved_env,
			"server_version": parsed.head.server_version,
			"folders_imported": len(parsed.folders),
			"globals_imported": len(parsed.globals),
			"folder_diffs": folder_diffs,
			"global_diffs": global_diffs,
		}
		if previous_version is not None and previous_version != parsed.head.server_version:
			result["server_version_changed_from"] = previous_version
		return json.dumps(result, indent=2)

	@mcp.tool
	async def schema_read(environment: str, folder_alias: str) -> str:
		"""Fetch the current normalized snapshot for a folder.

		Args:
		    environment: Environment name (e.g. "dev", "test", "prod").
		    folder_alias: The folder's alias.
		"""
		_require_authenticated()
		await store.migrate()
		folder = await store.get_folder(environment, folder_alias)
		if folder is None:
			raise KeyError(f"No schema snapshot for environment={environment!r} folder_alias={folder_alias!r}.")
		return json.dumps(folder, indent=2)

	@mcp.tool
	async def schema_globals_read(environment: str, group_type: str, object_name: str | None = None) -> str:
		"""Fetch the current snapshot for a Global Object group, or one object in it.

		Args:
		    environment: Environment name (e.g. "dev", "test", "prod").
		    group_type: Global Object group type (e.g. "Fields", "Scripts").
		    object_name: Specific object name within the group. Omit to list the whole group.
		"""
		_require_authenticated()
		await store.migrate()
		result = await store.get_global(environment, group_type, object_name)
		if object_name is not None and result is None:
			raise KeyError(
				f"No schema snapshot for environment={environment!r} group_type={group_type!r} "
				f"object_name={object_name!r}."
			)
		return json.dumps(result, indent=2)

	@mcp.tool
	async def schema_env_diff(folder_alias: str, environment_a: str, environment_b: str) -> str:
		"""Compare two environments' current snapshots for the same folder.

		Args:
		    folder_alias: The folder's alias.
		    environment_a: First environment name (the "old" side of the diff).
		    environment_b: Second environment name (the "new" side of the diff).
		"""
		_require_authenticated()
		await store.migrate()
		result = await store.diff_env(folder_alias, environment_a, environment_b)
		return json.dumps(result, indent=2)

	@mcp.tool
	async def schema_search(query: str, environment: str | None = None, limit: int = 20, offset: int = 0) -> str:
		"""Find fields/scripts/tasks/permissions/etc. by name substring across folders and Global Objects.

		Args:
		    query: Search terms (FTS5 trigram match).
		    environment: Optional environment name to restrict results to.
		    limit: Maximum results to return (default 20).
		    offset: Entries to skip (default 0).
		"""
		_require_authenticated()
		await store.migrate()
		results = await store.search(query, environment=environment, limit=limit, offset=offset)
		return json.dumps(results, indent=2)
