"""FastMCP instance and tool registration."""

from fastmcp import FastMCP

from gabos_mcp.tools import chm

mcp = FastMCP("gabos-mcp")

chm.register(mcp)
