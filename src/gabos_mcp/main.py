"""Entrypoint for the gabos-mcp server."""

from gabos_mcp.server import mcp


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
