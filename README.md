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

## Development

Interactive web UI with hot-reload:

```bash
uv run fastmcp dev inspector src/gabos_mcp/server.py --with-editable .
```
