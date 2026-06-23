"""MCP tools for telemetry analytics (admin-only)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from prefab_ui.app import PrefabApp
from prefab_ui.components import Badge, Column, DataTable, DataTableColumn, Heading, Metric, Muted, Row, Separator
from prefab_ui.components.charts import BarChart, ChartSeries

from gabos_mcp.utils.auth import get_github_login
from gabos_mcp.utils.telemetry import get_stats_data, is_admin

if TYPE_CHECKING:
	from fastmcp import FastMCP
	from prefab_ui.components.data_table import ExpandableRow


# (variant, css-color) per suffix — chart colors use the same CSS variables as badges
_SUFFIX_META: dict[str, tuple[str, str]] = {
	"_read": ("info", "var(--info)"),
	"_search": ("secondary", "var(--secondary-foreground)"),
	"_write": ("warning", "var(--warning)"),
	"_delete": ("destructive", "var(--destructive)"),
	"_stats": ("success", "var(--success)"),
}
_OTHER: tuple[str, str] = ("outline", "var(--muted-foreground)")
_SUFFIX_ORDER = {s: i for i, s in enumerate([*_SUFFIX_META, "_other"])}


def _tool_suffix(tool: str) -> str:
	for suffix in _SUFFIX_META:
		if tool.endswith(suffix):
			return suffix
	return "_other"


def _sort_tools(tools: list[tuple[str, int]]) -> list[tuple[str, int]]:
	return sorted(tools, key=lambda tc: (_SUFFIX_ORDER[_tool_suffix(tc[0])], tc[0]))


def _tool_badge(tool: str) -> Badge:
	variant, _ = _SUFFIX_META.get(_tool_suffix(tool), _OTHER)
	return Badge(tool, variant=variant)  # type: ignore[arg-type]


def _tool_bar_data_and_series(
	tools: list[tuple[str, int]],
) -> tuple[list[dict[str, Any]], list[ChartSeries]]:
	all_suffixes = [*_SUFFIX_META.keys(), "_other"]
	colors = {s: meta[1] for s, meta in _SUFFIX_META.items()} | {"_other": _OTHER[1]}
	active: set[str] = set()
	data: list[dict[str, Any]] = []
	for tool, count in tools:
		s = _tool_suffix(tool)
		active.add(s)
		data.append({"tool": tool, s: count})
	series = [
		ChartSeries(dataKey=sf, label=sf.lstrip("_") or "other", color=colors[sf])
		for sf in all_suffixes
		if sf in active
	]
	return data, series


def _tool_table_rows(
	tools: list[tuple[str, int]],
	tool_errors: dict[str, int],
	duration_stats: dict[str, dict[str, float]],
) -> list[dict[str, Any] | ExpandableRow]:
	rows = []
	for tool, count in tools:
		d = duration_stats.get(tool, {})
		rows.append(
			{
				"tool": _tool_badge(tool),
				"calls": str(count),
				"errors": str(tool_errors.get(tool, 0)),
				"min_ms": f"{d.get('min', 0):.1f}",
				"max_ms": f"{d.get('max', 0):.1f}",
				"mean_ms": f"{d.get('mean', 0):.1f}",
				"median_ms": f"{d.get('median', 0):.1f}",
				"std_ms": f"{d.get('std', 0):.1f}",
			}
		)
	return rows


def _build_dashboard(stats: dict[str, Any]) -> PrefabApp:
	tools = _sort_tools(stats["tools"])
	tool_bar_data, tool_bar_series = _tool_bar_data_and_series(tools)
	caller_bar_data = [{"caller": c, "calls": n} for c, n in stats["callers"]]
	view = Column(
		children=[
			Heading(content="Tool Call Statistics"),
			Row(
				children=[
					Metric(label="Total Calls", value=str(stats["total"])),
					Metric(label="Unique Tools", value=str(len(stats["tools"]))),
					Metric(label="Unique Callers", value=str(len(stats["callers"]))),
				],
				gap=4,
			),
			Separator(),
			Heading(content="Calls by Tool", level=2),
			BarChart(
				data=tool_bar_data,
				series=tool_bar_series,
				xAxis="tool",
				stacked=True,
				horizontal=True,
			),
			Separator(),
			Heading(content="Calls by User", level=2),
			BarChart(
				data=caller_bar_data,
				series=[ChartSeries(dataKey="calls", label="Calls")],
				xAxis="caller",
			),
			Separator(),
			Heading(content="Duration Statistics (ms)", level=2),
			DataTable(
				columns=[
					DataTableColumn(key="tool", header="Tool", sortable=True),
					DataTableColumn(key="calls", header="Calls", sortable=True),
					DataTableColumn(key="errors", header="Errors", sortable=True),
					DataTableColumn(key="min_ms", header="Min", sortable=True),
					DataTableColumn(key="max_ms", header="Max", sortable=True),
					DataTableColumn(key="mean_ms", header="Mean", sortable=True),
					DataTableColumn(key="median_ms", header="Median", sortable=True),
					DataTableColumn(key="std_ms", header="Std", sortable=True),
				],
				rows=_tool_table_rows(tools, stats["tool_errors"], stats["duration_stats"]),
			),
		],
		gap=6,
	)
	return PrefabApp(view=view, title="Telemetry Dashboard")


def register(mcp: FastMCP) -> None:
	"""Register telemetry tools on the given FastMCP instance."""

	@mcp.tool(app=True)
	async def telemetry_stats() -> PrefabApp:
		"""Show tool-call statistics: who called which tools and how often.

		Returns per-tool call counts, top callers, error counts, and duration
		statistics (min, max, mean, median, std). Only accessible to users
		listed in GABOS_ADMIN_USERS.
		"""
		caller = get_github_login()
		if not is_admin(caller):
			raise PermissionError("telemetry_stats is restricted to admins (GABOS_ADMIN_USERS).")
		stats = await get_stats_data()
		if stats is None:
			return PrefabApp(view=Muted(content="No telemetry data yet."), title="Telemetry Dashboard")
		return _build_dashboard(stats)
