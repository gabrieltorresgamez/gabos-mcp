"""FastMCP instance and tool registration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastmcp import FastMCP
from fastmcp.server.middleware.timing import DetailedTimingMiddleware
from starlette.responses import JSONResponse

from gabos_mcp.tools import chm, knowledge
from gabos_mcp.utils.auth import build_github_auth

if TYPE_CHECKING:
	from starlette.requests import Request

logging.basicConfig(level=logging.INFO)

auth = build_github_auth()
mcp = FastMCP("gabos-mcp", **({"auth": auth} if auth else {}))
mcp.add_middleware(DetailedTimingMiddleware())

chm.register(mcp)
knowledge.register(mcp)


@mcp.custom_route("/health", methods=["GET"])
async def http_health(request: Request) -> JSONResponse:
	"""Return server health status."""
	return JSONResponse({"status": "ok"})
