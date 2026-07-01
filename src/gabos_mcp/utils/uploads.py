"""FileUpload provider wiring for schema XML ingestion."""

from __future__ import annotations

import base64
import functools
from typing import TYPE_CHECKING, override

from fastmcp.apps.file_upload import FileUpload

from gabos_mcp.utils.auth import get_github_login

if TYPE_CHECKING:
	from fastmcp.server.context import Context


class SchemaFileUpload(FileUpload):
	"""FileUpload provider that exposes full-content read and delete.

	The base class truncates non-text uploads (XML included) to a 200-byte
	preview in ``on_read``, since it's designed for the model to skim files.
	schema_write needs the full document, so this subclass adds a
	same-store accessor that bypasses that truncation, plus a way to forget
	a file once it's been successfully imported (raw uploads are temp-only).
	"""

	@override
	def _get_scope_key(self, ctx: Context) -> str:
		"""Scope uploads by authenticated GitHub login instead of transport session ID.

		The base class partitions storage by ``ctx.session_id``, which is only
		stable within one live connection. The upload widget calls ``store_files``
		via its own UI action, a different request path than the assistant's plain
		tool calls (e.g. ``schema_write``) — a reconnect or token refresh between
		the two can silently swap in a new session ID, orphaning the uploaded file
		before it's ever read. Login is resolved from the (already-required) auth
		token on every request regardless of session/transport churn.

		Returns:
		    The authenticated caller's lowercased GitHub login, or "anonymous".
		"""
		return get_github_login()

	def get_raw_bytes(self, name: str, ctx: Context) -> bytes:
		"""Return the full decoded bytes of an uploaded file.

		Raises:
		    ValueError: If no file with this name was uploaded in this session.
		"""
		scope = self._get_scope_key(ctx)
		session_files = self._store.get(scope, {})
		if name not in session_files:
			available = list(session_files.keys())
			raise ValueError(f"File {name!r} not found. Available: {available}")
		return base64.b64decode(session_files[name]["data"])

	def forget(self, name: str, ctx: Context) -> None:
		"""Remove an uploaded file from storage (no long-term retention of raw uploads)."""
		scope = self._get_scope_key(ctx)
		self._store.get(scope, {}).pop(name, None)


@functools.cache
def get_schema_file_upload() -> SchemaFileUpload:
	"""Return the shared SchemaFileUpload provider instance."""
	return SchemaFileUpload(
		name="Schema Import",
		title="OMNITRACKER Schema Import",
		description=(
			"Drop an OMNITRACKER Export Documentation XML file here, then ask "
			"the assistant to import it via schema_write."
		),
		max_file_size=250 * 1024 * 1024,
	)
