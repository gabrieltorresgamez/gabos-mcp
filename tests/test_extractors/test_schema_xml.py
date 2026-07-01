"""Tests for OMNITRACKER Export Documentation XML parsing/normalization."""

from __future__ import annotations

import pytest

from gabos_mcp.extractors.schema_xml import (
	SchemaValidationError,
	check_root,
	parse_export,
	parse_head,
	parse_xml_bytes,
	validate_against_xsd,
)

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
  <GlobalObjects>
    <SchemaObjectGroup Type="Scripts">
      <SchemaObject id="1" active="Yes">
        <Name>Send Notification</Name>
        <Alias>SendNotification</Alias>
        <Description>Sends a notification email</Description>
        <SubType>VBScript</SubType>
        <Inherited>No</Inherited>
        <Attribute Name="Code">Dim x</Attribute>
      </SchemaObject>
    </SchemaObjectGroup>
  </GlobalObjects>
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
          <Attribute Name="Mandatory">Status = 'Open'</Attribute>
          <Attribute Name="FullText">No</Attribute>
          <Attribute Name="ToolTip">How urgent is it?</Attribute>
        </SchemaObject>
      </SchemaObjectGroup>
      <SchemaObjectGroup Type="Folder">
        <SchemaObject id="11">
          <Name>Sub Tickets</Name>
          <Alias>SubTickets</Alias>
          <Description>Nested folder</Description>
          <SubType IsNotUsed="Yes"></SubType>
          <Inherited>No</Inherited>
          <SchemaObjectGroup Type="Permissions">
            <SchemaObject id="200">
              <Name>Read Access</Name>
              <Alias>ReadAccess</Alias>
              <Description>Who can read</Description>
              <SubType IsNotUsed="Yes"></SubType>
              <Inherited>No</Inherited>
            </SchemaObject>
          </SchemaObjectGroup>
        </SchemaObject>
      </SchemaObjectGroup>
    </SchemaObject>
  </SchemaObjectGroup>
</ConfigurationDocumentation>
"""


class TestParseXmlBytes:
	def test_rejects_malformed_xml(self):
		with pytest.raises(SchemaValidationError, match="Malformed"):
			parse_xml_bytes(b"<not><closed>")

	def test_rejects_oversized_upload(self):
		with pytest.raises(SchemaValidationError, match="size cap"):
			parse_xml_bytes(b"x" * (300 * 1024 * 1024))

	def test_parses_well_formed_xml(self):
		root = parse_xml_bytes(_SAMPLE)
		assert root is not None


class TestCheckRoot:
	def test_accepts_expected_root(self):
		root = parse_xml_bytes(_SAMPLE)
		check_root(root)  # no error

	def test_rejects_wrong_root(self):
		root = parse_xml_bytes(b"<SomethingElse/>")
		with pytest.raises(SchemaValidationError, match="Unexpected root"):
			check_root(root)


class TestValidateAgainstXsd:
	def test_valid_document_passes(self):
		root = parse_xml_bytes(_SAMPLE)
		validate_against_xsd(root)  # no error

	def test_invalid_document_fails(self):
		root = parse_xml_bytes(b"""<?xml version="1.0"?>
        <ConfigurationDocumentation xmlns="http://www.omninet.de/schemas/configdocu/1.0">
          <NotAllowedElement/>
        </ConfigurationDocumentation>""")
		with pytest.raises(SchemaValidationError, match="XSD validation failed"):
			validate_against_xsd(root)


class TestParseHead:
	def test_extracts_head_fields(self):
		root = parse_xml_bytes(_SAMPLE)
		head = parse_head(root)
		assert head.server_name == "omni-dev01"
		assert head.server_port == "4000"
		assert head.server_version == "10.6.2"

	def test_missing_head_raises(self):
		root = parse_xml_bytes(b"""<?xml version="1.0"?>
        <ConfigurationDocumentation xmlns="http://www.omninet.de/schemas/configdocu/1.0"/>""")
		with pytest.raises(SchemaValidationError, match="Missing required 'Head'"):
			parse_head(root)

	def test_empty_server_name_raises(self):
		root = parse_xml_bytes(b"""<?xml version="1.0"?>
        <ConfigurationDocumentation xmlns="http://www.omninet.de/schemas/configdocu/1.0">
          <Head>
            <ServerName></ServerName>
            <ServerPort>4000</ServerPort>
            <ServerVersion>1.0</ServerVersion>
            <Date/><User/><Language/>
          </Head>
        </ConfigurationDocumentation>""")
		with pytest.raises(SchemaValidationError, match="ServerName"):
			parse_head(root)


class TestParseExport:
	def test_parses_head(self):
		parsed = parse_export(_SAMPLE)
		assert parsed.head.server_name == "omni-dev01"
		assert parsed.head.server_version == "10.6.2"

	def test_parses_global_objects(self):
		parsed = parse_export(_SAMPLE)
		assert len(parsed.globals) == 1
		g = parsed.globals[0]
		assert g.group_type == "Scripts"
		assert g.object_name == "SendNotification"
		assert g.data["attributes"]["Code"] == "Dim x"

	def test_parses_top_level_folder(self):
		parsed = parse_export(_SAMPLE)
		aliases = {f.alias for f in parsed.folders}
		assert "Tickets" in aliases

	def test_recurses_into_nested_folders(self):
		parsed = parse_export(_SAMPLE)
		aliases = {f.alias for f in parsed.folders}
		assert "SubTickets" in aliases

	def test_nested_folder_is_own_flat_record_not_nested_in_parent_data(self):
		parsed = parse_export(_SAMPLE)
		tickets = next(f for f in parsed.folders if f.alias == "Tickets")
		assert "Folder" not in tickets.data
		assert "Fields" in tickets.data

	def test_field_group_captures_mandatory_condition_and_tooltip(self):
		parsed = parse_export(_SAMPLE)
		tickets = next(f for f in parsed.folders if f.alias == "Tickets")
		priority = tickets.data["Fields"]["Priority"]
		assert priority["mandatory_condition"] == "Status = 'Open'"
		assert priority["tooltip"] == "How urgent is it?"
		assert priority["field_type"] == "Integer"

	def test_subfolder_content_lives_under_its_own_record(self):
		parsed = parse_export(_SAMPLE)
		sub = next(f for f in parsed.folders if f.alias == "SubTickets")
		assert "Permissions" in sub.data
		assert "ReadAccess" in sub.data["Permissions"]

	def test_no_folder_tree_no_globals_returns_empty(self):
		root = b"""<?xml version="1.0"?>
        <ConfigurationDocumentation xmlns="http://www.omninet.de/schemas/configdocu/1.0">
          <Head>
            <ServerName>x</ServerName><ServerPort>1</ServerPort><ServerVersion>1</ServerVersion>
            <Date/><User/><Language/>
          </Head>
        </ConfigurationDocumentation>"""
		parsed = parse_export(root)
		assert parsed.folders == []
		assert parsed.globals == []

	def test_is_not_used_flag_blanks_field(self):
		parsed = parse_export(_SAMPLE)
		tickets = next(f for f in parsed.folders if f.alias == "Tickets")
		assert tickets.name == "Tickets"
