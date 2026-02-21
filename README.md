# gabos-mcp

A personal MCP server for accessing and searching CHM (Compiled Help Manual) files.

## Features

- Full-text search across help documentation
- Retrieve page content in Markdown format
- Browse apps, sources, and pages with pagination
- Multi-app, multi-source support with automatic caching

## Connect

### IDE (Zed)

Add to `.zed/settings.json`:

```json
{
  "gabos-mcp": {
    "command": "uv",
    "args": ["run","--directory","/path/to/gabos-mcp","gabos-mcp"],
    "env": {"GABOS_CHM_FILES":"{\"MyApp\": {\"Admin Manual\": \"/path/to/admin.chm\", \"End User Manual\": \"/path/to/user.chm\"}, \"another_app\": {\"Reference\": \"/path/to/reference.chm\"}}"}
  }
}
```

### Development

Interactive web UI with hot-reload:

```bash
set -a && source .env && set +a && uv run fastmcp dev inspector src/gabos_mcp/server.py --with-editable .
```

Open `http://localhost:8000`
