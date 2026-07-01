# gabos-mcp

A personal MCP server.

## Setup

```bash
docker compose up
```

Copy `docker-compose.yml-example` to `docker-compose.yml` and configure via environment variables:

| Variable                      | Default                                        | Description                                       |
| ----------------------------- | ---------------------------------------------- | ------------------------------------------------- |
| `MCP_TRANSPORT`               | `streamable-http`                              | Transport protocol (`stdio` or `streamable-http`) |
| `MCP_HOST`                    | `0.0.0.0`                                      | Bind address (HTTP only)                          |
| `MCP_PORT`                    | `8000`                                         | Listen port (HTTP only)                           |
| `GABOS_CHM_FILES`             | `{}`                                           | JSON mapping of app names to CHM file paths       |
| `GABOS_CHM_CACHE_DIR`         | `~/.cache/gabos-mcp/chm`                       | CHM extraction/index cache directory              |
| `GABOS_KNOWLEDGE_DB`          | `~/.local/share/gabos-mcp/knowledge.db`        | Knowledge SQLite database path                    |
| `GABOS_AGENTS_DB`             | `~/.local/share/gabos-mcp/agents.db`           | Agents SQLite database path                       |
| `GABOS_SCHEMA_DB`             | `~/.local/share/gabos-mcp/schema.db`           | Schema SQLite database path                       |
| `GABOS_SCHEMA_ENVIRONMENTS`   | `{}`                                            | JSON mapping of environment name to `ServerName:ServerPort` |
| `GABOS_SCHEMA_ADMINS`         | _(none — nobody may import)_                    | Comma-separated GitHub logins allowed to run `schema_import` |
| `GABOS_BACKUP_DIR`            | _(none — backups disabled)_                    | Absolute path to the backup folder                |
| `GABOS_BACKUP_TIME`           | `02:00`                                        | Time of day to run the backup (24h, local time)   |
| `GABOS_BACKUP_RETENTION_DAYS` | `30`                                           | Days to keep backups (0 = keep forever)           |
| `GABOS_TELEMETRY_LOG`         | `~/.local/share/logs/gabos-mcp/tool_calls.log` | Path to the anonymous logfmt tool-call log        |
| `GITHUB_CLIENT_ID`            | _(none)_                                       | GitHub OAuth app client ID (enables OAuth)        |
| `GITHUB_CLIENT_SECRET`        | _(none)_                                       | GitHub OAuth app client secret                    |
| `MCP_BASE_URL`                | _(none)_                                       | Public URL of the server (e.g. `https://my.host`) |

When all three `GITHUB_*`/`MCP_BASE_URL` variables are set, the server requires GitHub OAuth 2.1 authentication. When any are missing, the server runs without auth (suitable for local stdio usage).

## Backups

Set `GABOS_BACKUP_DIR` to enable daily backups. The server copies both databases once per day using SQLite's Online Backup API and prunes files older than `GABOS_BACKUP_RETENTION_DAYS` days. Mount a volume so backups survive container restarts:

```yaml
volumes:
  - ./backups:/backups
environment:
  - GABOS_BACKUP_DIR=/backups
```

To restore, stop the server, copy the backup file over the original DB path (e.g. `cp backups/agents_2026-04-26.db ~/.local/share/gabos-mcp/agents.db`), then restart. The `schema.db` database is included in the same daily backup rotation.

## Connect

### Claude Desktop — Remote (OAuth)

Go to **Settings > Connectors > Add custom connector**, select "Streamable HTTP", and enter the server URL (e.g. `https://mcp.example.ch/mcp`). Claude Desktop handles the OAuth flow automatically.

### Claude Code — Remote (OAuth)

```bash
claude mcp add --transport http gabos-mcp https://mcp.fuet.ch/mcp
```

On first use, Claude Code opens your browser to complete the GitHub OAuth flow. Tokens are stored locally and refreshed automatically.

### Recommended allow-list

Tool suffixes reflect side-effect class, making per-tool allow-lists straightforward:

| Suffix             | Side effect              | Suggested setting |
| ------------------ | ------------------------ | ----------------- |
| `_read`, `_search` | Read-only                | **Always allow**  |
| `_write`           | Creates or modifies data | **Ask each time** |
| `_delete`          | Irreversible deletion    | **Ask each time** |

## Tools

Reads are open to all authenticated users; private items are hidden from non-owners without error. Writes and deletes are owner-only.

### Agents

Agents are domain expert personas stored in the database. Each has a system prompt and optional knowledge tags.

| Tool           | Description                                                                                      |
| -------------- | ------------------------------------------------------------------------------------------------ |
| `agent_search` | List all visible agents, optionally filtered by a query. Returns `id`, name, owner, description. |
| `agent_read`   | Fetch full details for a single agent by UUID (includes `system_prompt`, `knowledge_tags`).      |
| `agent_write`  | Create (`mode="create"`) or update (`mode="update"`) an agent definition. Owner-only.            |
| `agent_delete` | Delete an agent entirely. Owner-only. Tagged knowledge entries are **not** deleted.              |

### Knowledge

A shared, tag-filtered knowledge store. Knowledge tagged `agent:<name>` becomes part of that agent's context.

| Tool               | Description                                                                                                                                                                                        |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `knowledge_search` | Search entries by query (FTS, ranked by relevance) or browse by tag (ordered by recency). At least one of `query` or `tag` required. Returns metadata + score; fetch content via `knowledge_read`. |
| `knowledge_read`   | Fetch a single entry by `id` (includes full content).                                                                                                                                              |
| `knowledge_write`  | Create (`mode="create"`) or update (`mode="update"`) a knowledge entry. Owner-only for update.                                                                                                     |
| `knowledge_delete` | Delete a knowledge entry. Owner-only.                                                                                                                                                              |

### Schema (OMNITRACKER Export Documentation)

A ground-truth, auto-refreshed complement to `knowledge_*`: field definitions, mandatory rules,
scripts, permissions, views, and everything else an OMNITRACKER Export Documentation XML contains.
Each import fully replaces the prior snapshot for the folders/objects it covers — no history is
kept, the store always reflects the last import per environment.

**Producing an export**: in the OMNITRACKER Admin client, use **Export Documentation** to pick
folders and/or Global Objects from the schema tree and export to XML.

**Uploading**: drop the exported XML through the server's file-upload UI ("Schema Import"), then
ask the assistant to call `schema_import` with the uploaded file's name. The environment is
auto-detected from the export's `Head/ServerName` + `Head/ServerPort` against
`GABOS_SCHEMA_ENVIRONMENTS`; pass `environment` explicitly to override it. The raw upload is
deleted once parsing succeeds — nothing beyond the normalized snapshot is retained.

| Tool                  | Description                                                                                                        |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `schema_import`        | Parse an uploaded export XML and upsert it into the schema store. Admin-only (`GABOS_SCHEMA_ADMINS`).              |
| `schema_read`          | Fetch the current normalized snapshot for a folder, by `environment` + `folder_alias`.                             |
| `schema_globals_read`  | Fetch a Global Object group's snapshot, or one object in it, by `environment` + `group_type` (+ optional `object_name`). |
| `schema_env_diff`      | Compare two environments' current snapshots for the same folder — catches drift before promotion.                  |
| `schema_search`        | Full-text search over folders and Global Objects by name substring, optionally scoped to one `environment`.        |

Read tools require authentication (any authenticated user); only `schema_import` is admin-gated.

### Docs (CHM)

Read and search CHM documentation files configured via `GABOS_CHM_FILES`.

| Tool          | Description                                                                   |
| ------------- | ----------------------------------------------------------------------------- |
| `docs_search` | Full-text search across configured CHM apps.                                  |
| `docs_read`   | Read the full Markdown content of a page by `app`, `source`, and `page_path`. |

The cache lives under `GABOS_CHM_CACHE_DIR/<app>/<source>/`. Delete a subdirectory to invalidate it — the server rebuilds on next access without a restart:

```bash
rm -rf "$GABOS_CHM_CACHE_DIR/MYAPP/mysource"
```

### Telemetry

Every tool call is logged anonymously to `GABOS_TELEMETRY_LOG` (tool name, duration, success/error only — no caller identity is recorded).
