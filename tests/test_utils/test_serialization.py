"""Tests for the YAML-default/JSON-opt-in response serialization helper."""

from __future__ import annotations

import json

import yaml

from gabos_mcp.utils.serialization import dump_response


class TestDumpResponse:
	def test_defaults_to_yaml(self):
		result = dump_response({"a": 1, "b": {"c": 2}})
		assert yaml.safe_load(result) == {"a": 1, "b": {"c": 2}}
		assert "{" not in result

	def test_json_format_is_opt_in_and_equivalent(self):
		data = {"a": 1, "b": [1, 2, 3], "c": None}
		yaml_result = dump_response(data, "yaml")
		json_result = dump_response(data, "json")
		assert yaml.safe_load(yaml_result) == json.loads(json_result) == data

	def test_json_format_produces_strict_json(self):
		result = dump_response({"a": 1}, "json")
		assert json.loads(result) == {"a": 1}

	def test_none_round_trips(self):
		assert yaml.safe_load(dump_response(None)) is None
		assert json.loads(dump_response(None, "json")) is None

	def test_list_round_trips(self):
		data = [{"a": 1}, {"b": 2}]
		assert yaml.safe_load(dump_response(data)) == data
