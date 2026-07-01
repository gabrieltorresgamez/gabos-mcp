"""Tests for the SchemaStore."""

from __future__ import annotations

import pytest
import pytest_asyncio

from gabos_mcp.extractors.schema import SchemaStore


@pytest_asyncio.fixture
async def store(tmp_path):
	s = SchemaStore(db_path=str(tmp_path / "schema.db"))
	await s.migrate()
	yield s
	await s.close()


@pytest.mark.asyncio
class TestUpsertFolder:
	async def test_first_import_is_readable(self, store):
		data = {"Fields": {"Priority": {"alias": "Priority", "sub_type": "Integer"}}}
		await store.upsert_folder("dev", "Tickets", "Tickets", "10.0", data)
		got = await store.get_folder("dev", "Tickets")
		assert got["data"] == data

	async def test_reimport_overwrites_previous_data(self, store):
		await store.upsert_folder(
			"dev", "Tickets", "Tickets", "10.0", {"Fields": {"Priority": {"sub_type": "Integer"}}}
		)
		await store.upsert_folder("dev", "Tickets", "Tickets", "10.1", {"Fields": {"Priority": {"sub_type": "String"}}})
		got = await store.get_folder("dev", "Tickets")
		assert got["data"] == {"Fields": {"Priority": {"sub_type": "String"}}}
		assert got["server_version"] == "10.1"

	async def test_separate_environments_are_independent(self, store):
		await store.upsert_folder("dev", "Tickets", "Tickets", "10.0", {"Fields": {"A": {"sub_type": "x"}}})
		got = await store.get_folder("test", "Tickets")
		assert got is None


@pytest.mark.asyncio
class TestUpsertGlobal:
	async def test_first_import_is_readable(self, store):
		await store.upsert_global("dev", "Scripts", "SendNotification", "10.0", {"code": "Dim x"})
		got = await store.get_global("dev", "Scripts", "SendNotification")
		assert got["data"] == {"code": "Dim x"}

	async def test_reimport_overwrites_previous_data(self, store):
		await store.upsert_global("dev", "Scripts", "SendNotification", "10.0", {"code": "Dim x"})
		await store.upsert_global("dev", "Scripts", "SendNotification", "10.1", {"code": "Dim y"})
		got = await store.get_global("dev", "Scripts", "SendNotification")
		assert got["data"] == {"code": "Dim y"}
		assert got["server_version"] == "10.1"


@pytest.mark.asyncio
class TestGetFolder:
	async def test_returns_none_when_missing(self, store):
		assert await store.get_folder("dev", "Nope") is None

	async def test_returns_normalized_data(self, store):
		await store.upsert_folder("dev", "Tickets", "Tickets", "10.0", {"Fields": {"A": {"sub_type": "x"}}})
		got = await store.get_folder("dev", "Tickets")
		assert got["folder_name"] == "Tickets"
		assert got["data"] == {"Fields": {"A": {"sub_type": "x"}}}


@pytest.mark.asyncio
class TestGetGlobal:
	async def test_single_object(self, store):
		await store.upsert_global("dev", "Scripts", "SendNotification", "10.0", {"code": "x"})
		got = await store.get_global("dev", "Scripts", "SendNotification")
		assert got["data"] == {"code": "x"}

	async def test_missing_object_returns_none(self, store):
		assert await store.get_global("dev", "Scripts", "Nope") is None

	async def test_whole_group_listing(self, store):
		await store.upsert_global("dev", "Scripts", "A", "10.0", {"code": "1"})
		await store.upsert_global("dev", "Scripts", "B", "10.0", {"code": "2"})
		got = await store.get_global("dev", "Scripts")
		assert {g["object_name"] for g in got} == {"A", "B"}


@pytest.mark.asyncio
class TestDiffEnv:
	async def test_compares_two_environments(self, store):
		await store.upsert_folder("dev", "Tickets", "Tickets", "10.0", {"Fields": {"A": {"sub_type": "x"}}})
		await store.upsert_folder("prod", "Tickets", "Tickets", "10.0", {"Fields": {"B": {"sub_type": "y"}}})
		diff = await store.diff_env("Tickets", "dev", "prod")
		assert diff["added"] == ["Fields/B"]
		assert diff["removed"] == ["Fields/A"]

	async def test_missing_in_b_reports_found_in_b_false(self, store):
		await store.upsert_folder("dev", "Tickets", "Tickets", "10.0", {"Fields": {"A": {"sub_type": "x"}}})
		diff = await store.diff_env("Tickets", "dev", "prod")
		assert diff["found_in_a"] is True
		assert diff["found_in_b"] is False


@pytest.mark.asyncio
class TestSearch:
	async def test_finds_folder_by_content_substring(self, store):
		await store.upsert_folder(
			"dev", "Tickets", "Tickets", "10.0", {"Fields": {"Priority": {"sub_type": "Integer"}}}
		)
		results = await store.search("Priority")
		assert any(r["kind"] == "folder" and r["key1"] == "Tickets" for r in results)

	async def test_finds_global_by_object_name(self, store):
		await store.upsert_global("dev", "Scripts", "SendNotification", "10.0", {"code": "x"})
		results = await store.search("SendNotification")
		assert any(r["kind"] == "global" and r["key2"] == "SendNotification" for r in results)

	async def test_environment_filter(self, store):
		await store.upsert_folder(
			"dev", "Tickets", "Tickets", "10.0", {"Fields": {"Priority": {"sub_type": "Integer"}}}
		)
		await store.upsert_folder(
			"prod", "Tickets", "Tickets", "10.0", {"Fields": {"Priority": {"sub_type": "Integer"}}}
		)
		results = await store.search("Priority", environment="dev")
		assert all(r["environment"] == "dev" for r in results)


@pytest.mark.asyncio
class TestGetLastSeenVersion:
	async def test_none_when_no_imports(self, store):
		assert await store.get_last_seen_version("dev") is None

	async def test_returns_latest_version(self, store):
		await store.upsert_folder("dev", "Tickets", "Tickets", "10.0", {})
		assert await store.get_last_seen_version("dev") == "10.0"
