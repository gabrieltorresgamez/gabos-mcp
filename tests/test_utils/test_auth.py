"""Tests for the schema-admin allowlist check."""

from __future__ import annotations

import pytest

from gabos_mcp.utils.auth import is_schema_admin


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
	monkeypatch.delenv("GABOS_SCHEMA_ADMINS", raising=False)


class TestIsSchemaAdmin:
	def test_no_config_denies_everyone(self):
		assert is_schema_admin("alice") is False

	def test_listed_user_is_admin(self, monkeypatch):
		monkeypatch.setenv("GABOS_SCHEMA_ADMINS", "alice,bob")
		assert is_schema_admin("alice") is True
		assert is_schema_admin("bob") is True

	def test_unlisted_user_is_not_admin(self, monkeypatch):
		monkeypatch.setenv("GABOS_SCHEMA_ADMINS", "alice")
		assert is_schema_admin("bob") is False

	def test_case_insensitive(self, monkeypatch):
		monkeypatch.setenv("GABOS_SCHEMA_ADMINS", "Alice")
		assert is_schema_admin("alice") is True
