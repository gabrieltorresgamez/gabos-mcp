"""Tests for schema import environment resolution."""

from __future__ import annotations

import json

import pytest

from gabos_mcp.utils.environments import SchemaEnvironmentResolutionError, resolve_environment


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
	monkeypatch.delenv("GABOS_SCHEMA_ENVIRONMENTS", raising=False)


class TestResolveEnvironment:
	def test_override_bypasses_mapping(self, monkeypatch):
		monkeypatch.setenv("GABOS_SCHEMA_ENVIRONMENTS", json.dumps({"dev": "host:1"}))
		assert resolve_environment("other", "2", override="prod") == "prod"

	def test_resolves_from_mapping(self, monkeypatch):
		monkeypatch.setenv("GABOS_SCHEMA_ENVIRONMENTS", json.dumps({"dev": "omni-dev01:4000"}))
		assert resolve_environment("omni-dev01", "4000") == "dev"

	def test_no_match_raises_with_context(self, monkeypatch):
		monkeypatch.setenv("GABOS_SCHEMA_ENVIRONMENTS", json.dumps({"dev": "omni-dev01:4000"}))
		with pytest.raises(SchemaEnvironmentResolutionError) as exc_info:
			resolve_environment("unknown-host", "9999")
		assert exc_info.value.host_key == "unknown-host:9999"
		assert exc_info.value.known_environments == ["dev"]

	def test_empty_mapping_raises(self):
		with pytest.raises(SchemaEnvironmentResolutionError) as exc_info:
			resolve_environment("host", "1")
		assert exc_info.value.known_environments == []

	def test_malformed_mapping_treated_as_empty(self, monkeypatch):
		monkeypatch.setenv("GABOS_SCHEMA_ENVIRONMENTS", "not json")
		with pytest.raises(SchemaEnvironmentResolutionError):
			resolve_environment("host", "1")
