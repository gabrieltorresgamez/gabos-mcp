"""Tests for the schema-import environment allowlist (typo protection)."""

from __future__ import annotations

import pytest

from gabos_mcp.utils.environments import UnknownEnvironmentError, validate_environment


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
	monkeypatch.delenv("GABOS_SCHEMA_ENVIRONMENTS", raising=False)


class TestValidateEnvironment:
	def test_blank_environment_rejected_even_without_allowlist(self):
		with pytest.raises(UnknownEnvironmentError):
			validate_environment("")

	def test_whitespace_only_environment_rejected(self):
		with pytest.raises(UnknownEnvironmentError):
			validate_environment("   ")

	def test_any_non_blank_name_accepted_when_no_allowlist_configured(self):
		validate_environment("dev")  # no error

	def test_listed_name_accepted(self, monkeypatch):
		monkeypatch.setenv("GABOS_SCHEMA_ENVIRONMENTS", "dev,test,prod")
		validate_environment("prod")  # no error

	def test_unlisted_name_rejected_with_context(self, monkeypatch):
		monkeypatch.setenv("GABOS_SCHEMA_ENVIRONMENTS", "dev,test,prod")
		with pytest.raises(UnknownEnvironmentError) as exc_info:
			validate_environment("pordu")
		assert exc_info.value.environment == "pordu"
		assert exc_info.value.known_environments == ["dev", "prod", "test"]
