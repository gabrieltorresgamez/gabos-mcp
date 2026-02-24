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
| `GITHUB_CLIENT_ID`    | _(none)_          | GitHub OAuth app client ID (enables OAuth)        |
| `GITHUB_CLIENT_SECRET` | _(none)_         | GitHub OAuth app client secret                    |
| `MCP_BASE_URL`        | _(none)_          | Public URL of the server (e.g. `https://my.host`) |

When all three `GITHUB_*`/`MCP_BASE_URL` variables are set, the server requires GitHub OAuth 2.1 authentication. When any are missing, the server runs without auth (suitable for local stdio usage).

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

### Claude Desktop — Remote (OAuth)

Go to **Settings > Connectors > Add custom connector**, select "Streamable HTTP", and enter the server URL (e.g. `https://mcp.fuet.ch/mcp`). Claude Desktop handles the OAuth flow automatically — it registers itself via Dynamic Client Registration, opens a browser window for GitHub login, and manages token refresh.

### Claude Code — Remote (OAuth)

```bash
claude mcp add --transport http gabos-mcp https://mcp.fuet.ch/mcp
```

On first use, Claude Code opens your browser to complete the GitHub OAuth flow. Tokens are stored locally and refreshed automatically.

## Development

Interactive web UI with hot-reload:

```bash
uv run fastmcp dev inspector src/gabos_mcp/server.py --with-editable .
```
