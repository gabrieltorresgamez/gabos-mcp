"""Response serialization: YAML by default, JSON opt-in."""

from __future__ import annotations

import json
from typing import Any, Literal

import yaml

ResponseFormat = Literal["yaml", "json"]


def dump_response(data: dict[str, Any] | list[Any] | None, format: ResponseFormat = "yaml") -> str:
	"""Serialize tool response data as YAML (default) or JSON.

	YAML represents the same tree as JSON via indentation alone, without the
	brace/quote/comma overhead — pick "json" only for callers that need
	strict JSON (e.g. an existing programmatic parser).

	Returns:
	    The serialized response body.
	"""
	if format == "json":
		return json.dumps(data, indent=2)
	return yaml.dump(data, allow_unicode=True, sort_keys=False)
