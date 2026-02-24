"""FastMCP instance and tool registration."""

import os

from fastmcp import FastMCP

from gabos_mcp.tools import chm


def _build_auth():
    """Build OAuth auth provider if GitHub credentials are configured."""
    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    base_url = os.getenv("MCP_BASE_URL")

    if not (client_id and client_secret and base_url):
        return None

    from fastmcp.server.auth.providers.github import GitHubProvider

    return GitHubProvider(
        client_id=client_id,
        client_secret=client_secret,
        base_url=base_url,
    )


auth = _build_auth()
mcp = FastMCP("gabos-mcp", **({"auth": auth} if auth else {}))

chm.register(mcp)
