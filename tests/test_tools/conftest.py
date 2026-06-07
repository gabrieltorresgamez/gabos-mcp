"""Shared test helpers for test_tools."""

from __future__ import annotations

import pytest


@pytest.fixture
def make_mcp():
	"""Return a factory that builds a minimal FastMCP-like stub.

	The stub captures registered tools (via .tool) and resources (via .resource).
	"""

	def _factory():
		class Stub:
			def __init__(self) -> None:
				self.tools: dict = {}
				self.resources: dict = {}

			def tool(self, fn):
				self.tools[fn.__name__] = fn
				return fn

			def resource(self, uri):
				def decorator(fn):
					self.resources[uri] = fn
					return fn

				return decorator

		return Stub()

	return _factory
