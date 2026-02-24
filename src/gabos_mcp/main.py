"""Entrypoint for the gabos-mcp server."""

import json
import os

from gabos_mcp.server import mcp


def main():
    """Run the MCP server."""
    transport = os.getenv("MCP_TRANSPORT", "stdio")

    if transport == "stdio":
        mcp.run()
    elif transport == "streamable-http":
        auth_tokens_raw = os.getenv("MCP_AUTH_TOKENS")
        if auth_tokens_raw:
            allowed_tokens = set(json.loads(auth_tokens_raw))
            from fastmcp.server.auth.providers.debug import DebugTokenVerifier

            mcp.auth = DebugTokenVerifier(validate=lambda token: token in allowed_tokens)

        host = os.getenv("MCP_HOST", "127.0.0.1")
        port = int(os.getenv("MCP_PORT", "8000"))
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        raise ValueError(f"Unknown MCP_TRANSPORT: {transport!r}")


if __name__ == "__main__":
    main()
