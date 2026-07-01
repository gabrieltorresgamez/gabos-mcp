"""Pure parsing/normalization of OMNITRACKER "Export Documentation" XML.

No MCP dependency — this module only turns raw export bytes into plain
dataclasses/dicts. Storage lives in ``extractors/schema.py``.

Shape (per the bundled ``ConfigurationDocumentation.xsd``): the document root
carries ``Head`` (server identity), an optional ``GlobalObjects`` element (flat
``SchemaObjectGroup`` list), and an optional single top-level ``SchemaObjectGroup``
representing the folder tree. Every ``SchemaObjectGroup`` groups ``SchemaObject``
entries under a ``Type`` attribute; a ``SchemaObject`` may itself nest further
``SchemaObjectGroup`` elements ("normally the Subfolder" per the XSD annotation).

OMNITRACKER's own convention (confirmed against sample exports) marks the
folder-tree container with ``Type="Folder"``; that string is the one place
this module assumes a specific vocabulary rather than reading it generically.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from lxml import etree

_ROOT_LOCAL_NAME = "ConfigurationDocumentation"
_FOLDER_GROUP_TYPE = "folder"
_FIELDS_GROUP_TYPE = "fields"
_MAX_XML_SIZE = 250 * 1024 * 1024


class SchemaValidationError(Exception):
	"""Raised when an uploaded export fails validation before normalization."""


@dataclass
class ParsedHead:
	"""Identity/version info from the export's ``Head`` block."""

	server_name: str
	server_port: str
	server_version: str


@dataclass
class ParsedFolder:
	"""A single normalized folder record, keyed by its alias."""

	alias: str
	name: str
	data: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)


@dataclass
class ParsedGlobalObject:
	"""A single normalized Global Object, keyed by (group_type, object_name)."""

	group_type: str
	object_name: str
	data: dict[str, Any]


@dataclass
class ParsedExport:
	"""Fully parsed and normalized export document."""

	head: ParsedHead
	folders: list[ParsedFolder]
	globals: list[ParsedGlobalObject]


def _local_name(tag: str) -> str:
	return etree.QName(tag).localname


def _iter_children(elem: etree._Element, local_name: str) -> list[etree._Element]:
	return [c for c in elem if isinstance(c.tag, str) and _local_name(c.tag) == local_name]


def _find_child(elem: etree._Element, local_name: str) -> etree._Element | None:
	children = _iter_children(elem, local_name)
	return children[0] if children else None


def _mandatory_text(elem: etree._Element, local_name: str) -> str:
	"""Read a MandatoryFieldType child's text, honoring IsNotUsed.

	Returns:
	    The stripped text content, or "" if the child is absent or marked IsNotUsed.
	"""
	child = _find_child(elem, local_name)
	if child is None:
		return ""
	if (child.get("IsNotUsed") or "").strip().lower() == "yes":
		return ""
	return (child.text or "").strip()


def parse_xml_bytes(xml_bytes: bytes) -> etree._Element:
	"""Parse raw bytes into an lxml element, rejecting malformed XML.

	Returns:
	    The parsed document's root element.

	Raises:
	    SchemaValidationError: If the document is not well-formed or exceeds
	        the size cap.
	"""
	if len(xml_bytes) > _MAX_XML_SIZE:
		raise SchemaValidationError(f"Upload exceeds the size cap ({len(xml_bytes)} > {_MAX_XML_SIZE} bytes).")
	parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
	try:
		return etree.fromstring(xml_bytes, parser=parser)
	except etree.XMLSyntaxError as e:
		raise SchemaValidationError(f"Malformed XML: {e}") from e


def check_root(root: etree._Element) -> None:
	"""Confirm the document root is the expected element.

	Raises:
	    SchemaValidationError: If the root element's local name doesn't match.
	"""
	if _local_name(root.tag) != _ROOT_LOCAL_NAME:
		raise SchemaValidationError(
			f"Unexpected root element {_local_name(root.tag)!r}, expected {_ROOT_LOCAL_NAME!r}."
		)


@functools.cache
def _xsd_schema() -> etree.XMLSchema:
	xsd_path = resources.files("gabos_mcp.extractors.schemas").joinpath("ConfigurationDocumentation.xsd")
	with resources.as_file(xsd_path) as path:
		return etree.XMLSchema(etree.parse(str(path)))


def validate_against_xsd(root: etree._Element) -> None:
	"""Validate the document against the bundled ConfigurationDocumentation.xsd.

	Raises:
	    SchemaValidationError: If the document doesn't conform to the schema.
	"""
	schema = _xsd_schema()
	if not schema.validate(root):
		errors = "; ".join(str(e) for e in schema.error_log)
		raise SchemaValidationError(f"XSD validation failed: {errors}")


def parse_head(root: etree._Element) -> ParsedHead:
	"""Extract and sanity-check the ``Head`` block.

	Returns:
	    The parsed server identity and version.

	Raises:
	    SchemaValidationError: If Head, ServerName, or ServerPort is missing/empty.
	"""
	head = _find_child(root, "Head")
	if head is None:
		raise SchemaValidationError("Missing required 'Head' element.")

	def _text(local_name: str) -> str:
		child = _find_child(head, local_name)
		return (child.text or "").strip() if child is not None else ""

	server_name = _text("ServerName")
	server_port = _text("ServerPort")
	server_version = _text("ServerVersion")
	if not server_name or not server_port:
		raise SchemaValidationError("Head/ServerName and Head/ServerPort must be present and non-empty.")
	return ParsedHead(server_name=server_name, server_port=server_port, server_version=server_version)


def _normalize_item(item_elem: etree._Element) -> dict[str, Any]:
	result: dict[str, Any] = {"ref_name": item_elem.get("RefName")}
	static_text = item_elem.get("StaticText")
	if static_text is not None:
		result["static_text"] = static_text
	result["attributes"] = {
		a.get("Name") or "": _normalize_attribute(a) for a in _iter_children(item_elem, "Attribute")
	}
	return result


def _normalize_attribute(attr_elem: etree._Element) -> str | list[dict[str, Any]]:
	items = _iter_children(attr_elem, "Item")
	if items:
		return [_normalize_item(i) for i in items]
	nested_objects = _iter_children(attr_elem, "SchemaObject")
	if nested_objects:
		return [_normalize_object_attrs(o) for o in nested_objects]
	return (attr_elem.text or "").strip()


def _normalize_object_attrs(obj_elem: etree._Element) -> dict[str, Any]:
	attrs: dict[str, Any] = {
		"name": _mandatory_text(obj_elem, "Name"),
		"alias": _mandatory_text(obj_elem, "Alias"),
		"description": _mandatory_text(obj_elem, "Description"),
		"sub_type": _mandatory_text(obj_elem, "SubType"),
		"inherited": _mandatory_text(obj_elem, "Inherited"),
		"attributes": {a.get("Name") or "": _normalize_attribute(a) for a in _iter_children(obj_elem, "Attribute")},
	}
	obj_id = obj_elem.get("id")
	if obj_id:
		attrs["id"] = obj_id
	active = obj_elem.get("active")
	if active:
		attrs["active"] = active
	return attrs


def _normalize_object(obj_elem: etree._Element, group_type: str) -> tuple[str, dict[str, Any]]:
	attrs = _normalize_object_attrs(obj_elem)

	if group_type.strip().lower() == _FIELDS_GROUP_TYPE:
		attrs["field_type"] = attrs["sub_type"]
		attrs["mandatory_condition"] = _attr_ci(attrs["attributes"], "mandatory", "mandatorycondition")
		attrs["full_text"] = _attr_ci(attrs["attributes"], "fulltext", "fulltextindex")
		attrs["tooltip"] = _attr_ci(attrs["attributes"], "tooltip")

	key = attrs["alias"] or attrs["name"] or attrs.get("id", "")
	return key, attrs


def _attr_ci(attributes: dict[str, Any], *candidates: str) -> str | list[dict[str, Any]] | None:
	lowered = {k.strip().lower(): v for k, v in attributes.items()}
	for candidate in candidates:
		if candidate in lowered:
			return lowered[candidate]
	return None


def _normalize_group(group_elem: etree._Element) -> tuple[str, dict[str, dict[str, Any]]]:
	group_type = group_elem.get("Type") or "Unknown"
	objects: dict[str, dict[str, Any]] = {}
	for obj_elem in _iter_children(group_elem, "SchemaObject"):
		key, attrs = _normalize_object(obj_elem, group_type)
		objects[key or f"__unnamed_{len(objects)}"] = attrs
	return group_type, objects


def _collect_folders(obj_elem: etree._Element, out: list[ParsedFolder]) -> None:
	"""Recursively normalize a folder SchemaObject and its subfolders, flattening into ``out``."""
	name = _mandatory_text(obj_elem, "Name")
	alias = _mandatory_text(obj_elem, "Alias") or name
	data: dict[str, dict[str, dict[str, Any]]] = {}
	for group_elem in _iter_children(obj_elem, "SchemaObjectGroup"):
		group_type = (group_elem.get("Type") or "").strip().lower()
		if group_type == _FOLDER_GROUP_TYPE:
			for sub_obj in _iter_children(group_elem, "SchemaObject"):
				_collect_folders(sub_obj, out)
		else:
			key, objects = _normalize_group(group_elem)
			data[key] = objects
	out.append(ParsedFolder(alias=alias, name=name, data=data))


def _normalize_globals(global_objects_elem: etree._Element) -> list[ParsedGlobalObject]:
	result: list[ParsedGlobalObject] = []
	for group_elem in _iter_children(global_objects_elem, "SchemaObjectGroup"):
		group_type, objects = _normalize_group(group_elem)
		for object_name, attrs in objects.items():
			result.append(ParsedGlobalObject(group_type=group_type, object_name=object_name, data=attrs))
	return result


def parse_export(xml_bytes: bytes, *, validate_xsd: bool = True) -> ParsedExport:
	"""Run the full validation + normalization pipeline over a raw export upload.

	Layers applied in order: well-formedness, root/namespace check, XSD
	validation (bundled ``ConfigurationDocumentation.xsd``), Head sanity check.
	Every group present in the document — folder tree, Global Objects, or both
	— is walked and normalized; nothing is filtered by type or size.

	Any validation layer failing (well-formedness, root check, XSD, Head
	sanity) propagates its SchemaValidationError to the caller.

	Args:
	    xml_bytes: Raw uploaded file content.
	    validate_xsd: Set False to skip XSD validation (tests only).

	Returns:
	    The fully normalized export: head identity, flat folder records, and
	    flat Global Object records.
	"""
	root = parse_xml_bytes(xml_bytes)
	check_root(root)
	if validate_xsd:
		validate_against_xsd(root)
	head = parse_head(root)

	folders: list[ParsedFolder] = []
	root_group = _find_child(root, "SchemaObjectGroup")
	if root_group is not None and (root_group.get("Type") or "").strip().lower() == _FOLDER_GROUP_TYPE:
		for obj_elem in _iter_children(root_group, "SchemaObject"):
			_collect_folders(obj_elem, folders)

	globals_list: list[ParsedGlobalObject] = []
	global_objects_elem = _find_child(root, "GlobalObjects")
	if global_objects_elem is not None:
		globals_list = _normalize_globals(global_objects_elem)

	return ParsedExport(head=head, folders=folders, globals=globals_list)
