"""FastMCP instance and tool registration."""

from dotenv import find_dotenv, load_dotenv
from fastmcp import FastMCP

from gabos_mcp.tools import chm

_env_file = find_dotenv(usecwd=True)
if not _env_file:
    raise FileNotFoundError("Missing .env file — copy .env-example and fill in your values.")
load_dotenv(_env_file)

mcp = FastMCP("gabos-mcp")

chm.register(mcp)
