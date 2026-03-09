"""FastMCP instance and tool registration."""

import logging

from fastmcp import FastMCP
from fastmcp.server.middleware.timing import DetailedTimingMiddleware

from gabos_mcp.tools import chm, knowledge
from gabos_mcp.utils.auth import build_github_auth

logging.basicConfig(level=logging.INFO)

auth = build_github_auth()
mcp = FastMCP("gabos-mcp", **({"auth": auth} if auth else {}))
mcp.add_middleware(DetailedTimingMiddleware())

chm.register(mcp)
knowledge.register(mcp)
