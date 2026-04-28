"""FastMCP instance and tool registration."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from fastmcp import FastMCP
from fastmcp.server.middleware.timing import DetailedTimingMiddleware
from starlette.responses import JSONResponse

from gabos_mcp.tools import agents, chm, knowledge
from gabos_mcp.utils.auth import build_github_auth
from gabos_mcp.utils.backup import backup_scheduler

if TYPE_CHECKING:
	from collections.abc import AsyncGenerator

	from starlette.requests import Request

logging.basicConfig(level=logging.INFO)


@contextlib.asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncGenerator[None]:
	task = asyncio.create_task(backup_scheduler())
	try:
		yield
	finally:
		task.cancel()
		with contextlib.suppress(asyncio.CancelledError):
			await task


auth = build_github_auth()
mcp = FastMCP("gabos-mcp", lifespan=_lifespan, **({"auth": auth} if auth else {}))
mcp.add_middleware(DetailedTimingMiddleware())

agents.register(mcp)
chm.register(mcp)
knowledge.register(mcp)


@mcp.custom_route("/health", methods=["GET"])
async def http_health(_request: Request) -> JSONResponse:  # noqa: RUF029
	"""Return server health status."""
	return JSONResponse({"status": "ok"})
