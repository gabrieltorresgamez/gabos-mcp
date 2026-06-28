"""Tests for the anonymous telemetry utilities."""

from __future__ import annotations

import pytest

from gabos_mcp.utils.telemetry import (
	_format_logfmt,
	log_tool_call,
)

# ── _format_logfmt ───────────────────────────────────────────────────────────


def test_format_logfmt_simple():
	line = _format_logfmt({"tool": "knowledge_search", "ok": True})
	assert line == "tool=knowledge_search ok=true"


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


# ── log_tool_call ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_tool_call_creates_file(tmp_path, monkeypatch):
	log_file = tmp_path / "calls.log"
	monkeypatch.setenv("GABOS_TELEMETRY_LOG", str(log_file))

	await log_tool_call("knowledge_search", 42.0, True)

	assert log_file.exists()
	content = log_file.read_text()
	assert "tool=knowledge_search" in content
	assert "ok=true" in content


def test_log_tool_call_is_anonymous(tmp_path, monkeypatch):
	# The log record must not contain any caller / user identity field.
	line = _format_logfmt({"ts": "2026-01-01T00:00:00Z", "tool": "foo", "duration_ms": 1.0, "ok": True})
	assert "caller" not in line


@pytest.mark.asyncio
async def test_log_tool_call_failure_includes_error(tmp_path, monkeypatch):
	log_file = tmp_path / "calls.log"
	monkeypatch.setenv("GABOS_TELEMETRY_LOG", str(log_file))

	await log_tool_call("agent_read", 5.0, False, "not found")

	content = log_file.read_text()
	assert "ok=false" in content
	assert "error=" in content
	assert "not found" in content


@pytest.mark.asyncio
async def test_log_tool_call_appends(tmp_path, monkeypatch):
	log_file = tmp_path / "calls.log"
	monkeypatch.setenv("GABOS_TELEMETRY_LOG", str(log_file))

	await log_tool_call("tool_a", 1.0, True)
	await log_tool_call("tool_b", 2.0, True)

	lines = [ln for ln in log_file.read_text().splitlines() if ln]
	assert len(lines) == 2
