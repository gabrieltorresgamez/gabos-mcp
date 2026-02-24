"""Entrypoint for the gabos-mcp server."""

import os

from dotenv import find_dotenv, load_dotenv


def main():
    """Load environment and run the MCP server."""
    env_file = find_dotenv(usecwd=True)
    if not env_file:
        raise FileNotFoundError("Missing .env file — copy .env-example and fill in your values.")
    load_dotenv(env_file)

    # Import after env is loaded so modules can read env vars at import time
    from gabos_mcp.server import mcp

    transport = os.getenv("MCP_TRANSPORT", "stdio")

    if transport == "stdio":
        mcp.run()
    elif transport == "streamable-http":
        host = os.getenv("MCP_HOST", "127.0.0.1")
        port = int(os.getenv("MCP_PORT", "8000"))
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        raise ValueError(f"Unknown MCP_TRANSPORT: {transport!r}")


if __name__ == "__main__":
    main()
