# gabos-mcp

A personal MCP server.

## Connect

### IDE (Zed)

Add to `.zed/settings.json`:

```json
{
  "gabos-mcp": {
    "command": "uv",
    "args": ["run", "--directory", "/path/to/gabos-mcp", "gabos-mcp"]
  }
}
```

### Development

Interactive web UI with hot-reload:

```bash
uv run fastmcp dev inspector src/gabos_mcp/server.py --with-editable .
```

Open `http://localhost:8000`

Configuration is loaded automatically from a `.env` file in the project root (see `.env.example`).
