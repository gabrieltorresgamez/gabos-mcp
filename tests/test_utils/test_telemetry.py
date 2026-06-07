"""Tests for the telemetry utilities."""

from __future__ import annotations

import pytest

from gabos_mcp.utils.telemetry import (
	_compute_stats,
	_duration_stats,
	_format_logfmt,
	_parse_logfmt,
	get_admin_users,
	get_stats_data,
	is_admin,
	log_tool_call,
)

# ── _format_logfmt ───────────────────────────────────────────────────────────


def test_format_logfmt_simple():
	line = _format_logfmt({"tool": "knowledge_search", "caller": "alice", "ok": True})
	assert line == "tool=knowledge_search caller=alice ok=true"


def test_format_logfmt_float():
	line = _format_logfmt({"duration_ms": 42.5})
	assert line == "duration_ms=42.50"


def test_format_logfmt_quotes_spaces():
	line = _format_logfmt({"error": "something went wrong"})
	assert line == 'error="something went wrong"'


def test_format_logfmt_quotes_equals():
	line = _format_logfmt({"msg": "a=b"})
	assert line == 'msg="a=b"'


def test_format_logfmt_skips_none():
	line = _format_logfmt({"tool": "x", "error": None})
	assert "error" not in line


def test_format_logfmt_false_bool():
	line = _format_logfmt({"ok": False})
	assert line == "ok=false"


def test_format_logfmt_escapes_newlines():
	line = _format_logfmt({"error": "line one\nline two"})
	assert "\n" not in line
	assert "\\n" in line


# ── _parse_logfmt ────────────────────────────────────────────────────────────


def test_parse_logfmt_simple():
	rec = _parse_logfmt("tool=knowledge_search caller=alice ok=true")
	assert rec == {"tool": "knowledge_search", "caller": "alice", "ok": "true"}


def test_parse_logfmt_quoted_value():
	rec = _parse_logfmt('error="something went wrong"')
	assert rec["error"] == "something went wrong"


def test_parse_logfmt_quoted_with_escaped_quote():
	rec = _parse_logfmt('error="it said \\"hello\\""')
	assert rec["error"] == 'it said "hello"'


def test_parse_logfmt_unescapes_newlines():
	line = _format_logfmt({"error": "line one\nline two"})
	rec = _parse_logfmt(line)
	assert rec["error"] == "line one\nline two"


def test_parse_logfmt_roundtrip():
	original: dict[str, object] = {
		"tool": "agent_read",
		"caller": "bob",
		"duration_ms": 12.34,
		"ok": False,
		"error": "not found",
	}
	line = _format_logfmt(original)
	parsed = _parse_logfmt(line)
	assert parsed["tool"] == "agent_read"
	assert parsed["caller"] == "bob"
	assert parsed["ok"] == "false"
	assert parsed["error"] == "not found"


# ── is_admin / get_admin_users ───────────────────────────────────────────────


def test_is_admin_true(monkeypatch):
	monkeypatch.setenv("GABOS_ADMIN_USERS", "alice,bob")
	assert is_admin("alice")
	assert is_admin("BOB")


def test_is_admin_false(monkeypatch):
	monkeypatch.setenv("GABOS_ADMIN_USERS", "alice")
	assert not is_admin("charlie")


def test_is_admin_empty_env(monkeypatch):
	monkeypatch.setenv("GABOS_ADMIN_USERS", "")
	assert not is_admin("alice")


def test_get_admin_users_strips_whitespace(monkeypatch):
	monkeypatch.setenv("GABOS_ADMIN_USERS", " alice , bob ")
	assert get_admin_users() == {"alice", "bob"}


# ── log_tool_call ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_tool_call_creates_file(tmp_path, monkeypatch):
	log_file = tmp_path / "calls.log"
	monkeypatch.setenv("GABOS_TELEMETRY_LOG", str(log_file))

	await log_tool_call("knowledge_search", "alice", 42.0, True)

	assert log_file.exists()
	content = log_file.read_text()
	assert "tool=knowledge_search" in content
	assert "caller=alice" in content
	assert "ok=true" in content


@pytest.mark.asyncio
async def test_log_tool_call_failure_includes_error(tmp_path, monkeypatch):
	log_file = tmp_path / "calls.log"
	monkeypatch.setenv("GABOS_TELEMETRY_LOG", str(log_file))

	await log_tool_call("agent_read", "bob", 5.0, False, "not found")

	content = log_file.read_text()
	assert "ok=false" in content
	assert "error=" in content
	assert "not found" in content


@pytest.mark.asyncio
async def test_log_tool_call_appends(tmp_path, monkeypatch):
	log_file = tmp_path / "calls.log"
	monkeypatch.setenv("GABOS_TELEMETRY_LOG", str(log_file))

	await log_tool_call("tool_a", "alice", 1.0, True)
	await log_tool_call("tool_b", "alice", 2.0, True)

	lines = [ln for ln in log_file.read_text().splitlines() if ln]
	assert len(lines) == 2


# ── get_stats_data ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_stats_data_no_file(tmp_path, monkeypatch):
	monkeypatch.setenv("GABOS_TELEMETRY_LOG", str(tmp_path / "missing.log"))
	assert await get_stats_data() is None


@pytest.mark.asyncio
async def test_get_stats_data_returns_dict(tmp_path, monkeypatch):
	log_file = tmp_path / "calls.log"
	monkeypatch.setenv("GABOS_TELEMETRY_LOG", str(log_file))
	await log_tool_call("foo", "alice", 1.0, True)
	result = await get_stats_data()
	assert result is not None
	assert result["total"] == 1
	assert "duration_stats" in result


# ── _duration_stats ───────────────────────────────────────────────────────────


def test_duration_stats_empty():
	assert _duration_stats([]) == {}


def test_duration_stats_single_sample():
	d = _duration_stats([5.0])
	assert d["min"] == pytest.approx(5.0)
	assert d["max"] == pytest.approx(5.0)
	assert d["mean"] == pytest.approx(5.0)
	assert d["median"] == pytest.approx(5.0)
	assert d["std"] == pytest.approx(0.0)


def test_duration_stats_two_samples():
	d = _duration_stats([1.0, 3.0])
	assert d["min"] == pytest.approx(1.0)
	assert d["max"] == pytest.approx(3.0)
	assert d["mean"] == pytest.approx(2.0)
	assert d["median"] == pytest.approx(2.0)
	# sample std dev of [1, 3]: sqrt(((1-2)^2 + (3-2)^2) / 1) = sqrt(2)
	assert d["std"] == pytest.approx(2**0.5)


def test_duration_stats_odd_count():
	d = _duration_stats([1.0, 2.0, 9.0])
	assert d["median"] == pytest.approx(2.0)
	assert d["mean"] == pytest.approx(4.0)


# ── _compute_stats ───────────────────────────────────────────────────────────


def test_compute_stats_empty():
	stats = _compute_stats([], 5)
	assert stats["total"] == 0
	assert stats["top_tools"] == []
	assert stats["top_callers"] == []


def test_compute_stats_counts():
	lines = [
		"ts=2026-01-01T00:00:00Z tool=foo caller=alice duration_ms=1.00 ok=true",
		"ts=2026-01-01T00:00:01Z tool=foo caller=alice duration_ms=2.00 ok=false",
		"ts=2026-01-01T00:00:02Z tool=bar caller=bob duration_ms=3.00 ok=true",
	]
	stats = _compute_stats(lines, 10)
	assert stats["total"] == 3
	assert stats["top_tools"][0] == ("foo", 2)
	assert stats["top_callers"][0] == ("alice", 2)
	assert stats["tool_errors"]["foo"] == 1
	assert "bar" not in stats["tool_errors"]
	assert stats["duration_stats"]["foo"]["mean"] == pytest.approx(1.5)
	assert stats["duration_stats"]["bar"]["min"] == pytest.approx(3.0)


def test_compute_stats_skips_blank_lines():
	lines = ["", "  ", "ts=2026-01-01T00:00:00Z tool=x caller=a duration_ms=1.00 ok=true"]
	stats = _compute_stats(lines, 5)
	assert stats["total"] == 1


def test_compute_stats_skips_multiline_error_continuation():
	# Simulates a log entry whose error value spans multiple lines (written before
	# newline-escaping was added). Continuation lines must not inflate counts.
	lines = [
		'ts=2026-01-01T00:00:00Z tool=foo caller=alice duration_ms=1.00 ok=false error="bad\n',
		"continuation line\n",
		'another line"\n',
	]
	stats = _compute_stats(lines, 10)
	assert stats["total"] == 1
	assert stats["top_tools"][0] == ("foo", 1)
	assert "unknown" not in dict(stats["top_tools"])
