# gabos-mcp

A personal MCP server.

## Docker

```bash
docker compose up
```

Configure via `docker-compose.yml` (copy from `docker-compose.yml-example`). Environment variables:

| Variable               | Default                                 | Description                                       |
| ---------------------- | --------------------------------------- | ------------------------------------------------- |
| `MCP_TRANSPORT`        | `streamable-http`                       | Transport protocol (`stdio` or `streamable-http`) |
| `MCP_HOST`             | `0.0.0.0`                               | Bind address (HTTP only)                          |
| `MCP_PORT`             | `8000`                                  | Listen port (HTTP only)                           |
| `GABOS_CHM_FILES`      | `{}`                                    | JSON mapping of apps to CHM file paths            |
| `GABOS_CHM_CACHE_DIR`  | _(auto)_                                | Override CHM cache directory                      |
| `GABOS_KNOWLEDGE_DB`   | `~/.local/share/gabos-mcp/knowledge.db` | Path to the knowledge SQLite database             |
| `GABOS_AGENTS_DB`      | `~/.local/share/gabos-mcp/agents.db`    | Path to the agents SQLite database                |
| `ANTHROPIC_API_KEY`    | _(none)_                                | Anthropic API key (required for `agent_ask`)      |
| `GITHUB_CLIENT_ID`     | _(none)_                                | GitHub OAuth app client ID (enables OAuth)        |
| `GITHUB_CLIENT_SECRET` | _(none)_                                | GitHub OAuth app client secret                    |
| `MCP_BASE_URL`         | _(none)_                                | Public URL of the server (e.g. `https://my.host`) |

When all three `GITHUB_*`/`MCP_BASE_URL` variables are set, the server requires GitHub OAuth 2.1 authentication. When any are missing, the server runs without auth (suitable for local stdio usage).

## Connect

### Claude Desktop — Remote (OAuth)

Go to **Settings > Connectors > Add custom connector**, select "Streamable HTTP", and enter the server URL (e.g. `https://mcp.example.ch/mcp`). Claude Desktop handles the OAuth flow automatically — it registers itself via Dynamic Client Registration, opens a browser window for GitHub login, and manages token refresh.

### Claude Code — Remote (OAuth)

```bash
claude mcp add --transport http gabos-mcp https://mcp.fuet.ch/mcp
```

On first use, Claude Code opens your browser to complete the GitHub OAuth flow. Tokens are stored locally and refreshed automatically.
