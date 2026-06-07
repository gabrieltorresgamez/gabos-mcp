"""Tool-call telemetry: logfmt persistence, admin helpers, and FastMCP middleware."""

from __future__ import annotations

import asyncio
import os
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

import aiofiles
from fastmcp.server.middleware.middleware import Middleware
from platformdirs import user_log_path

from gabos_mcp.utils.auth import get_github_login

if TYPE_CHECKING:
	from fastmcp.server.middleware.middleware import CallNext, MiddlewareContext

_lock = asyncio.Lock()


def _log_path() -> Path:
	"""Return the resolved telemetry log file path."""
	raw = os.getenv("GABOS_TELEMETRY_LOG", "")
	if raw:
		return Path(raw)
	return user_log_path("gabos-mcp") / "tool_calls.log"


def get_admin_users() -> set[str]:
	"""Return the set of GitHub handles granted admin access.

	Returns:
	    Lowercase GitHub handles from GABOS_ADMIN_USERS, or empty set if unset.
	"""
	raw = os.getenv("GABOS_ADMIN_USERS", "")
	return {u.strip().lower() for u in raw.split(",") if u.strip()}


def is_admin(login: str) -> bool:
	"""Return True if login is in the GABOS_ADMIN_USERS allow-list.

	Returns:
	    True when GABOS_ADMIN_USERS is non-empty and login matches an entry.
	"""
	admins = get_admin_users()
	return bool(admins) and login.lower() in admins


def _logfmt_value(v: object) -> str:
	if isinstance(v, bool):
		return str(v).lower()
	if isinstance(v, float):
		return f"{v:.2f}"
	s = str(v)
	if " " in s or '"' in s or "=" in s:
		escaped = s.replace('"', '\\"')
		return f'"{escaped}"'
	return s


def _format_logfmt(fields: dict[str, object]) -> str:
	return " ".join(f"{k}={_logfmt_value(v)}" for k, v in fields.items() if v is not None)


def _parse_logfmt(line: str) -> dict[str, str]:
	result: dict[str, str] = {}
	i = 0
	line = line.rstrip("\n")
	n = len(line)
	while i < n:
		while i < n and line[i] == " ":
			i += 1
		if i >= n:
			break
		eq = line.find("=", i)
		if eq == -1:
			break
		key = line[i:eq]
		i = eq + 1
		if i < n and line[i] == '"':
			i += 1
			start = i
			while i < n and line[i] != '"':
				if line[i] == "\\" and i + 1 < n:
					i += 1
				i += 1
			value = line[start:i].replace('\\"', '"')
			i += 1
		else:
			start = i
			while i < n and line[i] != " ":
				i += 1
			value = line[start:i]
		result[key] = value
	return result


def _try_float(s: str) -> float | None:
	try:
		return float(s)
	except ValueError:
		return None


def _duration_stats(durations: list[float]) -> dict[str, float]:
	n = len(durations)
	if n == 0:
		return {}
	sorted_d = sorted(durations)
	mean = sum(sorted_d) / n
	median = sorted_d[n // 2] if n % 2 == 1 else (sorted_d[n // 2 - 1] + sorted_d[n // 2]) / 2.0
	std = (sum((d - mean) ** 2 for d in sorted_d) / (n - 1)) ** 0.5 if n > 1 else 0.0
	return {"min": sorted_d[0], "max": sorted_d[-1], "mean": mean, "median": median, "std": std}


async def log_tool_call(
	tool_name: str,
	caller: str,
	duration_ms: float,
	success: bool,
	error: str | None = None,
) -> None:
	"""Append one tool-call record to the telemetry log in logfmt format."""
	fields: dict[str, object] = {
		"ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
		"tool": tool_name,
		"caller": caller,
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


def _compute_stats(lines: list[str], top_n: int) -> dict[str, Any]:
	tool_counts: Counter[str] = Counter()
	caller_counts: Counter[str] = Counter()
	caller_tool: defaultdict[str, Counter[str]] = defaultdict(Counter)
	tool_errors: Counter[str] = Counter()
	tool_durations: defaultdict[str, list[float]] = defaultdict(list)

	for line in lines:
		if not line.strip():
			continue
		rec = _parse_logfmt(line)
		tool = rec.get("tool", "unknown")
		caller = rec.get("caller", "unknown")
		ok = rec.get("ok", "true") == "true"
		tool_counts[tool] += 1
		caller_counts[caller] += 1
		caller_tool[caller][tool] += 1
		if not ok:
			tool_errors[tool] += 1
		dur = _try_float(rec.get("duration_ms", ""))
		if dur is not None:
			tool_durations[tool].append(dur)

	per_caller: dict[str, list[tuple[str, int]]] = {
		c: caller_tool[c].most_common(top_n) for c, _ in caller_counts.most_common(top_n)
	}
	return {
		"total": sum(tool_counts.values()),
		"top_tools": tool_counts.most_common(top_n),
		"top_callers": caller_counts.most_common(top_n),
		"per_caller": per_caller,
		"tool_errors": dict(tool_errors.most_common()),
		"duration_stats": {t: _duration_stats(ds) for t, ds in tool_durations.items()},
	}


def _render_stats(stats: dict[str, Any], top_n: int) -> str:
	out = [f"Tool Call Statistics (top {top_n})", "=" * 44, f"Total calls: {stats['total']}"]

	out.append("\nTop tools by call count:")
	for tool, count in stats["top_tools"]:
		err = stats["tool_errors"].get(tool, 0)
		err_str = f" ({err} error{'s' if err != 1 else ''})" if err else ""
		out.append(f"  {tool}: {count}{err_str}")

	out.append("\nTop callers:")
	for caller, count in stats["top_callers"]:
		out.append(f"  {caller}: {count}")

	out.append("\nPer-caller breakdown:")
	for caller, tool_stats in stats["per_caller"].items():
		out.append(f"  {caller}:")
		for tool, count in tool_stats:
			out.append(f"    {tool}: {count}")

	return "\n".join(out)


async def get_stats_data(top_n: int = 10) -> dict[str, Any] | None:
	"""Read the telemetry log and return the raw stats dict.

	Returns:
	    Stats dict, or None if no telemetry data exists yet.
	"""
	path = _log_path()
	if not path.exists():
		return None
	async with aiofiles.open(path) as f:
		lines = await f.readlines()
	if not lines:
		return None
	return _compute_stats(lines, top_n)


async def read_stats(top_n: int = 10) -> str:
	"""Read the telemetry log and return a formatted stats report.

	Returns:
	    Human-readable statistics text, or a message when no data exists yet.
	"""
	stats = await get_stats_data(top_n)
	if stats is None:
		return "No telemetry data yet."
	return _render_stats(stats, top_n)


class TelemetryMiddleware(Middleware):
	"""FastMCP middleware that records every tool call to the telemetry log."""

	@override
	async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext) -> Any:
		"""Intercept tool calls; log tool name, caller, duration, and success/failure.

		Returns:
		    The unmodified result from the next middleware or tool handler.
		"""
		tool_name: str = getattr(context.message, "name", "unknown")
		caller = get_github_login()
		start = time.perf_counter()
		try:
			result = await call_next(context)
		except Exception as e:
			await log_tool_call(tool_name, caller, (time.perf_counter() - start) * 1000, False, str(e))
			raise
		else:
			await log_tool_call(tool_name, caller, (time.perf_counter() - start) * 1000, True)
			return result
