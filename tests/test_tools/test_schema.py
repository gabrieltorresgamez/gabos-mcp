"""Tests for schema_import, schema_read, schema_globals_read, schema_env_diff, schema_search."""

from __future__ import annotations

import base64
import json
from typing import cast
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastmcp.server.context import Context

from gabos_mcp.extractors.schema import SchemaStore
from gabos_mcp.tools.schema import register
from gabos_mcp.utils.uploads import SchemaFileUpload

_SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<ConfigurationDocumentation xmlns="http://www.omninet.de/schemas/configdocu/1.0" version="1.0">
  <Head>
    <ServerName>omni-dev01</ServerName>
    <ServerPort>4000</ServerPort>
    <ServerVersion>10.6.2</ServerVersion>
    <Date>2026-06-01</Date>
    <User>admin</User>
    <Language>EN</Language>
  </Head>
  <SchemaObjectGroup Type="Folder">
    <SchemaObject id="10" active="Yes">
      <Name>Tickets</Name>
      <Alias>Tickets</Alias>
      <Description>Ticket folder</Description>
      <SubType IsNotUsed="Yes"></SubType>
      <Inherited>No</Inherited>
      <SchemaObjectGroup Type="Fields">
        <SchemaObject id="100">
          <Name>Priority</Name>
          <Alias>Priority</Alias>
          <Description>Ticket priority</Description>
          <SubType>Integer</SubType>
          <Inherited>No</Inherited>
        </SchemaObject>
      </SchemaObjectGroup>
    </SchemaObject>
  </SchemaObjectGroup>
</ConfigurationDocumentation>
"""


class FakeCtx:
	session_id = "sess1"


@pytest_asyncio.fixture
async def store(tmp_path):
	s = SchemaStore(db_path=str(tmp_path / "schema.db"))
	await s.migrate()
	yield s
	await s.close()


@pytest.fixture
def file_upload():
	fu = SchemaFileUpload(name="test-upload")
	fu.on_store(
		[{"name": "export.xml", "size": len(_SAMPLE), "type": "text/xml", "data": base64.b64encode(_SAMPLE).decode()}],
		cast("Context", FakeCtx()),
	)
	return fu


@pytest_asyncio.fixture
async def tools(store, file_upload, make_mcp):
	mcp = make_mcp()
	with (
		patch("gabos_mcp.tools.schema.get_schema_store", return_value=store),
		patch("gabos_mcp.tools.schema.get_schema_file_upload", return_value=file_upload),
	):
		register(mcp)
	return mcp.tools


@pytest.fixture(autouse=True)
def _env_config(monkeypatch):
	monkeypatch.setenv("GABOS_SCHEMA_ADMINS", "alice")


@pytest.mark.asyncio
class TestSchemaImport:
	async def test_admin_can_import(self, tools):
		with patch("gabos_mcp.tools.schema.get_github_login", return_value="alice"):
			result = json.loads(await tools["schema_import"](file_name="export.xml", environment="dev", ctx=FakeCtx()))
		assert result["environment"] == "dev"
		assert result["folders_imported"] == 1

	async def test_non_admin_denied(self, tools):
		with (
			patch("gabos_mcp.tools.schema.get_github_login", return_value="bob"),
			pytest.raises(PermissionError),
		):
			await tools["schema_import"](file_name="export.xml", environment="dev", ctx=FakeCtx())

	async def test_anonymous_denied(self, tools):
		with (
			patch("gabos_mcp.tools.schema.get_github_login", return_value="anonymous"),
			pytest.raises(PermissionError),
		):
			await tools["schema_import"](file_name="export.xml", environment="dev", ctx=FakeCtx())

	async def test_deletes_upload_after_success(self, tools, file_upload):
		with patch("gabos_mcp.tools.schema.get_github_login", return_value="alice"):
			await tools["schema_import"](file_name="export.xml", environment="dev", ctx=FakeCtx())
		assert file_upload.on_list(FakeCtx()) == []


@pytest.mark.asyncio
class TestSchemaRead:
	async def test_authenticated_can_read(self, tools):
		with patch("gabos_mcp.tools.schema.get_github_login", return_value="alice"):
			await tools["schema_import"](file_name="export.xml", environment="dev", ctx=FakeCtx())
			result = json.loads(await tools["schema_read"](environment="dev", folder_alias="Tickets"))
		assert result["folder_name"] == "Tickets"

	async def test_anonymous_denied(self, tools):
		with (
			patch("gabos_mcp.tools.schema.get_github_login", return_value="anonymous"),
			pytest.raises(PermissionError),
		):
			await tools["schema_read"](environment="dev", folder_alias="Tickets")

	async def test_missing_folder_raises_key_error(self, tools):
		with (
			patch("gabos_mcp.tools.schema.get_github_login", return_value="alice"),
			pytest.raises(KeyError),
		):
			await tools["schema_read"](environment="dev", folder_alias="Nope")


@pytest.mark.asyncio
class TestSchemaGlobalsRead:
	async def test_empty_group_listing_returns_empty_list(self, tools):
		with patch("gabos_mcp.tools.schema.get_github_login", return_value="alice"):
			result = json.loads(await tools["schema_globals_read"](environment="dev", group_type="Scripts"))
		assert result == []

	async def test_missing_single_object_raises_key_error(self, tools):
		with (
			patch("gabos_mcp.tools.schema.get_github_login", return_value="alice"),
			pytest.raises(KeyError),
		):
			await tools["schema_globals_read"](environment="dev", group_type="Scripts", object_name="Nope")


@pytest.mark.asyncio
class TestSchemaEnvDiff:
	async def test_compares_environments(self, tools):
		with patch("gabos_mcp.tools.schema.get_github_login", return_value="alice"):
			await tools["schema_import"](file_name="export.xml", environment="dev", ctx=FakeCtx())
			result = json.loads(
				await tools["schema_env_diff"](folder_alias="Tickets", environment_a="dev", environment_b="test")
			)
		assert result["found_in_a"] is True
		assert result["found_in_b"] is False


@pytest.mark.asyncio
class TestSchemaSearch:
	async def test_finds_imported_field(self, tools):
		with patch("gabos_mcp.tools.schema.get_github_login", return_value="alice"):
			await tools["schema_import"](file_name="export.xml", environment="dev", ctx=FakeCtx())
			result = json.loads(await tools["schema_search"](query="Priority"))
		assert len(result) >= 1
