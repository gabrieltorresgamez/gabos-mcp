# gabos-mcp

A personal MCP server.

## Docker

```bash
docker compose up
```

Configure via `docker-compose.yml` (copy from `docker-compose.yml-example`). Environment variables:

| Variable              | Default           | Description                                       |
| --------------------- | ----------------- | ------------------------------------------------- |
| `MCP_TRANSPORT`       | `streamable-http` | Transport protocol (`stdio` or `streamable-http`) |
| `MCP_HOST`            | `0.0.0.0`         | Bind address (HTTP only)                          |
| `MCP_PORT`            | `8000`            | Listen port (HTTP only)                           |
| `GABOS_CHM_FILES`     | `{}`              | JSON mapping of apps to CHM file paths            |
| `GABOS_CHM_CACHE_DIR` | _(auto)_          | Override cache directory                          |
| `MCP_AUTH_TOKENS`     | _(none)_          | JSON list of allowed bearer tokens (HTTP only)    |

Generate a token with:

```bash
openssl rand -hex 64
```

## Connect

### Claude Desktop (stdio)

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "gabos-mcp": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/gabos-mcp-repo", "gabos-mcp"]
    }
  }
}
```

### IDE (Zed) — Local (stdio)

Add to `.zed/settings.json`:

```json
{
  "gabos-mcp": {
    "command": "uv",
    "args": ["run", "--directory", "/path/to/gabos-mcp-repo", "gabos-mcp"]
  }
}
```

### Claude Desktop — Remote (HTTP)

Go to **Settings > Connectors > Add custom connector**, select "Streamable HTTP", and enter the server URL. Note: Claude Desktop uses OAuth for remote auth, not bearer tokens.

### IDE (Zed) — Remote (HTTP)

Add to `.zed/settings.json`:

```json
{
  "gabos-mcp": {
    "url": "http://your-server:8000/mcp",
    "headers": {
      "Authorization": "Bearer <TOKEN>"
    }
  }
}
```

### Claude Code — Remote (HTTP)

```bash
claude mcp add --transport http gabos-mcp http://your-server:8000/mcp \
  --header "Authorization: Bearer <TOKEN>"
```

## Development

Interactive web UI with hot-reload:

```bash
uv run fastmcp dev inspector src/gabos_mcp/server.py --with-editable .
```
