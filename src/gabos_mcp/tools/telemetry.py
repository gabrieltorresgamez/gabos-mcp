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


_SUFFIX_VARIANT: dict[str, str] = {
	"_read": "info",
	"_search": "secondary",
	"_write": "warning",
	"_delete": "destructive",
	"_stats": "default",
}


def _tool_badge(tool: str) -> Badge:
	for suffix, variant in _SUFFIX_VARIANT.items():
		if tool.endswith(suffix):
			return Badge(tool, variant=variant)  # type: ignore[arg-type]
	return Badge(tool, variant="outline")


def _tool_table_rows(stats: dict[str, Any]) -> list[dict[str, Any] | ExpandableRow]:
	rows = []
	for tool, count in stats["tools"]:
		errors = stats["tool_errors"].get(tool, 0)
		d = stats["duration_stats"].get(tool, {})
		rows.append(
			{
				"tool": _tool_badge(tool),
				"calls": str(count),
				"errors": str(errors),
				"min_ms": f"{d.get('min', 0):.1f}",
				"max_ms": f"{d.get('max', 0):.1f}",
				"mean_ms": f"{d.get('mean', 0):.1f}",
				"median_ms": f"{d.get('median', 0):.1f}",
				"std_ms": f"{d.get('std', 0):.1f}",
			}
		)
	return rows


def _build_dashboard(stats: dict[str, Any]) -> PrefabApp:
	tool_bar_data = [{"tool": t, "calls": c} for t, c in stats["tools"]]
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
				series=[ChartSeries(dataKey="calls", label="Calls")],
				xAxis="tool",
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
				rows=_tool_table_rows(stats),
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
