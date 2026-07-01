"""Tests for SchemaFileUpload's login-scoped storage."""

from __future__ import annotations

import base64
from typing import cast
from unittest.mock import patch

from fastmcp.server.context import Context

from gabos_mcp.utils.uploads import SchemaFileUpload


class FakeCtxA:
	session_id = "session-a"


class FakeCtxB:
	session_id = "session-b"


class TestScopeKey:
	def test_scoped_by_login_survives_a_different_session_id(self):
		fu = SchemaFileUpload(name="test-upload")
		data = base64.b64encode(b"<xml/>").decode()

		with patch("gabos_mcp.utils.uploads.get_github_login", return_value="alice"):
			fu.on_store(
				[{"name": "export.xml", "size": 7, "type": "text/xml", "data": data}],
				cast("Context", FakeCtxA()),
			)
			listed = fu.on_list(cast("Context", FakeCtxB()))

		assert [f["name"] for f in listed] == ["export.xml"]

	def test_different_logins_do_not_share_uploads(self):
		fu = SchemaFileUpload(name="test-upload")
		data = base64.b64encode(b"<xml/>").decode()

		with patch("gabos_mcp.utils.uploads.get_github_login", return_value="alice"):
			fu.on_store(
				[{"name": "export.xml", "size": 7, "type": "text/xml", "data": data}],
				cast("Context", FakeCtxA()),
			)

		with patch("gabos_mcp.utils.uploads.get_github_login", return_value="bob"):
			listed = fu.on_list(cast("Context", FakeCtxA()))

		assert listed == []
