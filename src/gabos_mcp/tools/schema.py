"""MCP tools for the ground-truth schema store (OMNITRACKER Export Documentation)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fastmcp.server.context import Context

from gabos_mcp.extractors.schema_xml import SchemaValidationError, parse_export
from gabos_mcp.utils.auth import get_github_login, is_schema_admin
from gabos_mcp.utils.environments import UnknownEnvironmentError, validate_environment
from gabos_mcp.utils.stores import get_schema_store
from gabos_mcp.utils.uploads import get_schema_file_upload

if TYPE_CHECKING:
	from fastmcp import FastMCP


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
	async def schema_write(file_name: str, environment: str, ctx: Context) -> str:
		"""Parse an uploaded OMNITRACKER Export Documentation XML and upsert it into the schema store.

		Upload the XML via the Schema Import file-upload UI first, then call this
		with the uploaded file's name. Admin-only (GABOS_SCHEMA_ADMINS).

		environment must be non-blank, and must be one of GABOS_SCHEMA_ENVIRONMENTS
		if that allowlist is configured — this catches typos before they create a
		stray, permanently separate environment bucket.

		Every folder and Global Object group present in the export is normalized
		and stored — nothing is filtered by type or size. Re-importing a
		folder/object overwrites its row. The raw upload is deleted once parsing
		has been attempted (success or failure); nothing is retained beyond the
		normalized snapshot.

		Args:
		    file_name: Name of a file previously uploaded via the file-upload UI.
		    environment: Environment name to store this snapshot under (e.g. "dev", "prod").
		    ctx: Injected request context (session scoping for the uploaded file).
		"""
		user = _require_authenticated()
		if not is_schema_admin(user):
			raise PermissionError("Only schema admins may import schema exports.")

		try:
			validate_environment(environment)
		except UnknownEnvironmentError as e:
			return json.dumps(
				{"error": str(e), "environment": e.environment, "known_environments": e.known_environments}
			)

		await store.migrate()

		raw_bytes = file_upload.get_raw_bytes(file_name, ctx)

		try:
			parsed = parse_export(raw_bytes)
		except SchemaValidationError as e:
			return json.dumps({"error": str(e)})
		finally:
			file_upload.forget(file_name, ctx)

		previous_version = await store.get_last_seen_version(environment)

		try:
			for folder in parsed.folders:
				await store.upsert_folder(
					environment=environment,
					folder_alias=folder.alias,
					folder_name=folder.name,
					server_version=parsed.head.server_version,
					data=folder.data,
					commit=False,
				)

			for obj in parsed.globals:
				await store.upsert_global(
					environment=environment,
					group_type=obj.group_type,
					object_name=obj.object_name,
					server_version=parsed.head.server_version,
					data=obj.data,
					commit=False,
				)
		except Exception:
			await store.rollback()
			raise

		await store.commit()

		result = {
			"environment": environment,
			"server_version": parsed.head.server_version,
			"folders_imported": len(parsed.folders),
			"globals_imported": len(parsed.globals),
		}
		if previous_version is not None and previous_version != parsed.head.server_version:
			result["server_version_changed_from"] = previous_version
		return json.dumps(result, indent=2)

	@mcp.tool
	async def schema_read(environment: str, folder_alias: str, categories: list[str] | None = None) -> str:
		"""Fetch a folder's normalized snapshot, in full or as a summary.

		Without `categories`, returns a summary only: each category name (Fields,
		Permissions, Scripts, Forms, Print layouts, Views, etc.) mapped to its entry
		count — cheap enough to always call first. Pass `categories` to get full
		detail for just those categories, e.g. `categories=["Fields"]` to see every
		field without pulling in hundreds of unrelated Permissions/Scripts entries.

		Args:
		    environment: Environment name (e.g. "dev", "test", "prod").
		    folder_alias: The folder's alias.
		    categories: Category names to return in full (e.g. ["Fields", "Scripts"]).
		        Omit to get the cheap summary (category -> entry count) instead.
		"""
		_require_authenticated()
		await store.migrate()
		folder = await store.get_folder_view(environment, folder_alias, categories)
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
	async def schema_diff_read(folder_alias: str, environment_a: str, environment_b: str) -> str:
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
