"""FastMCP instance and tool registration."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from fastmcp import FastMCP
from starlette.responses import JSONResponse

from gabos_mcp.tools import agents, chm, knowledge, schema
from gabos_mcp.utils.auth import build_github_auth
from gabos_mcp.utils.backup import backup_scheduler
from gabos_mcp.utils.telemetry import TelemetryMiddleware
from gabos_mcp.utils.uploads import get_schema_file_upload

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
mcp.add_middleware(TelemetryMiddleware())

agents.register(mcp)
chm.register(mcp)
knowledge.register(mcp)
schema.register(mcp)
mcp.add_provider(get_schema_file_upload())


@mcp.custom_route("/health", methods=["GET"])
async def http_health(_request: Request) -> JSONResponse:  # noqa: RUF029
	"""Return server health status."""
	return JSONResponse({"status": "ok"})
