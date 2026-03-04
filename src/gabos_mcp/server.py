"""FastMCP instance and tool registration."""

from fastmcp import FastMCP

from gabos_mcp.tools import chm, knowledge
from gabos_mcp.utils.auth import build_github_auth

auth = build_github_auth()
mcp = FastMCP("gabos-mcp", **({"auth": auth} if auth else {}))

chm.register(mcp)
knowledge.register(mcp)
