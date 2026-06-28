"""Anonymous tool-call telemetry: logfmt persistence and FastMCP middleware."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

import aiofiles
from fastmcp.server.middleware.middleware import Middleware
from platformdirs import user_log_path

if TYPE_CHECKING:
	from fastmcp.server.middleware.middleware import CallNext, MiddlewareContext

_lock = asyncio.Lock()


def _log_path() -> Path:
	"""Return the resolved telemetry log file path."""
	raw = os.getenv("GABOS_TELEMETRY_LOG", "")
	if raw:
		return Path(raw)
	return user_log_path("gabos-mcp") / "tool_calls.log"


def _logfmt_value(v: object) -> str:
	if isinstance(v, bool):
		return str(v).lower()
	if isinstance(v, float):
		return f"{v:.2f}"
	s = str(v)
	if " " in s or '"' in s or "=" in s or "\n" in s:
		escaped = s.replace('"', '\\"').replace("\n", "\\n")
		return f'"{escaped}"'
	return s


def _format_logfmt(fields: dict[str, object]) -> str:
	return " ".join(f"{k}={_logfmt_value(v)}" for k, v in fields.items() if v is not None)


async def log_tool_call(
	tool_name: str,
	duration_ms: float,
	success: bool,
	error: str | None = None,
) -> None:
	"""Append one anonymous tool-call record to the telemetry log in logfmt format."""
	fields: dict[str, object] = {
		"ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
		"tool": tool_name,
		"duration_ms": duration_ms,
		"ok": success,
	}
	if error:
		fields["error"] = error
	line = _format_logfmt(fields) + "\n"
	path = _log_path()
	async with _lock:
		path.parent.mkdir(parents=True, exist_ok=True)
		async with aiofiles.open(path, "a") as f:
			await f.write(line)


class TelemetryMiddleware(Middleware):
	"""FastMCP middleware that records every tool call anonymously to the telemetry log."""

	@override
	async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext) -> Any:
		"""Intercept tool calls; log tool name, duration, and success/failure (no caller info).

		Returns:
		    The unmodified result from the next middleware or tool handler.
		"""
		tool_name: str = getattr(context.message, "name", "unknown")
		start = time.perf_counter()
		try:
			result = await call_next(context)
		except Exception as e:
			await log_tool_call(tool_name, (time.perf_counter() - start) * 1000, False, str(e))
			raise
		else:
			await log_tool_call(tool_name, (time.perf_counter() - start) * 1000, True)
			return result
