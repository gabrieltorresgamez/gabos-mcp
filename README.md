# gabos-mcp

A personal MCP server.

## Docker

```bash
docker compose up
```

Configure via `docker-compose.yml` (copy from `docker-compose.yml-example`). Environment variables:

| Variable                      | Default                                 | Description                                       |
| ----------------------------- | --------------------------------------- | ------------------------------------------------- |
| `MCP_TRANSPORT`               | `streamable-http`                       | Transport protocol (`stdio` or `streamable-http`) |
| `MCP_HOST`                    | `0.0.0.0`                               | Bind address (HTTP only)                          |
| `MCP_PORT`                    | `8000`                                  | Listen port (HTTP only)                           |
| `GABOS_CHM_FILES`             | `{}`                                    | JSON mapping of apps to CHM file paths            |
| `GABOS_CHM_CACHE_DIR`         | `~/.cache/gabos-mcp/chm`                | CHM extraction/index cache directory              |
| `GABOS_KNOWLEDGE_DB`          | `~/.local/share/gabos-mcp/knowledge.db` | Path to the knowledge SQLite database             |
| `GABOS_AGENTS_DB`             | `~/.local/share/gabos-mcp/agents.db`    | Path to the agents SQLite database                |
| `GABOS_BACKUP_DIR`            | _(none — backups disabled)_                              | Absolute path to the backup folder                          |
| `GABOS_BACKUP_TIME`           | `02:00`                                                  | Time of day to run the backup (24h, local time)             |
| `GABOS_BACKUP_RETENTION_DAYS` | `30`                                                     | Days to keep backups (0 = keep forever)                     |
| `GABOS_TELEMETRY_LOG`         | `~/.local/share/logs/gabos-mcp/tool_calls.log`           | Path to the logfmt tool-call log                            |
| `GABOS_ADMIN_USERS`           | _(none — `telemetry_stats` inaccessible)_                | Comma-separated GitHub handles allowed to call admin tools  |
| `GITHUB_CLIENT_ID`            | _(none)_                                                 | GitHub OAuth app client ID (enables OAuth)                  |
| `GITHUB_CLIENT_SECRET`        | _(none)_                                                 | GitHub OAuth app client secret                              |
| `MCP_BASE_URL`                | _(none)_                                                 | Public URL of the server (e.g. `https://my.host`)           |

When all three `GITHUB_*`/`MCP_BASE_URL` variables are set, the server requires GitHub OAuth 2.1 authentication. When any are missing, the server runs without auth (suitable for local stdio usage).

### Backups

Set `GABOS_BACKUP_DIR` to enable daily backups. The server copies both databases once per day using SQLite's Online Backup API (safe against concurrent writes) and deletes files older than `GABOS_BACKUP_RETENTION_DAYS` days. If a backup already exists for the current day it is skipped. Mount a volume in Docker so backups survive container restarts:

```yaml
volumes:
  - ./backups:/backups
environment:
  - GABOS_BACKUP_DIR=/backups
```

**Restore (manual):**

1. Stop the server.
2. Copy the backup file over the original database path, e.g. `cp backups/agents_2026-04-26.db ~/.local/share/gabos-mcp/agents.db`.
3. Start the server.

Backup files are plain SQLite databases and can be inspected with any SQLite client.

## Connect

### Claude Desktop — Remote (OAuth)

Go to **Settings > Connectors > Add custom connector**, select "Streamable HTTP", and enter the server URL (e.g. `https://mcp.example.ch/mcp`). Claude Desktop handles the OAuth flow automatically — it registers itself via Dynamic Client Registration, opens a browser window for GitHub login, and manages token refresh.

### Recommended Claude Desktop allow-list

Tools are named with a suffix that reflects their side-effect class, making per-tool allow-lists straightforward:

| Suffix            | Side effect              | Suggested Claude Desktop setting |
| ----------------- | ------------------------ | -------------------------------- |
| `_read`, `_search` | Read-only               | **Always allow**                 |
| `_write`          | Creates or modifies data | **Allow once per session**       |
| `_delete`         | Irreversible deletion    | **Ask each time**                |

## Tools

Tools are grouped by module and named `module_verb` so they sort alphabetically by domain. There are 11 tools total.

### Permission model

- **Reads are open** to all authenticated users. Private items (agents and knowledge with `shared=false`) are hidden from non-owners but do not raise errors.
- **Writes and deletes are owner-only.** Only the resource owner may update or delete it.
- **Agent-tag ownership:** adding a tag of the form `agent:<name>` or `agent:<name>:folder:<key>` to a knowledge entry requires you to own that agent.
- **Admin-only tools:** `telemetry_stats` requires the caller to be listed in `GABOS_ADMIN_USERS`.

### Agents

Agents are domain expert personas stored in the database. Each agent has a system prompt and optional knowledge tags. Context assembly is fully manual — the model searches for what it needs rather than being force-fed.

**Agent Q&A flow:**

1. `agent_search()` → pick agent, note `id` and `name`
2. `agent_read(id=...)` → `system_prompt`, `knowledge_tags`
3. Search the agent's knowledge. Always search the `agent:<name>` baseline:
   `knowledge_search(query, tag="agent:<name>")`. If `knowledge_tags` is
   non-empty, run one additional `knowledge_search` per listed tag and merge
   the results. Most agents leave `knowledge_tags` empty and rely on the
   baseline alone.
4. `knowledge_read(id=...)` for entries worth reading
5. `docs_search` / `docs_read` if CHM documentation is relevant
6. Answer using `system_prompt` as persona
7. `knowledge_write(tags=["agent:<name>"])` to persist new facts

| Tool             | Description                                                                                      |
| ---------------- | ------------------------------------------------------------------------------------------------ |
| `agent_search`   | List all visible agents, optionally filtered by a query. Returns `id`, name, owner, description. |
| `agent_read`     | Fetch full details for a single agent by UUID (includes `system_prompt`, `knowledge_tags`).      |
| `agent_write`    | Create (`mode="create"`) or update (`mode="update"`) an agent definition. Owner-only.            |
| `agent_delete`   | Delete an agent entirely. Owner-only. Knowledge entries tagged to the agent are **not** deleted. |

**agent_write modes:**

- `mode="create"` — `name`, `description`, `system_prompt` required; `knowledge_tags` and `shared` optional.
- `mode="update"` — `name_or_id` required; all other fields are partial overrides (omit to keep existing value).

### Knowledge

A shared, tag-filtered knowledge store. Knowledge tagged `agent:<name>` becomes part of that agent's context.

| Tool               | Description                                                                                              |
| ------------------ | -------------------------------------------------------------------------------------------------------- |
| `knowledge_search` | Full-text search over entries, ranked by relevance. Returns metadata + score only; fetch content via `knowledge_read`. |
| `knowledge_read`   | Fetch a single entry by `id` (includes full content). Use `knowledge_search` to discover IDs.           |
| `knowledge_write`  | Create (`mode="create"`) or update (`mode="update"`) a knowledge entry. Owner-only for update.          |
| `knowledge_delete` | Delete a knowledge entry. Owner-only.                                                                    |

**knowledge_write modes:**

- `mode="create"` — `title` and `content` required; `id` must be omitted; `tags` and `shared` optional (`shared` defaults to `false`).
- `mode="update"` — `id` required; all other fields are partial overrides (omit to keep existing value, including `shared`).

**knowledge_search** params: `query`, `tag?`, `owner?`, `limit?`, `offset?`. The `score` field is the FTS5 BM25 rank; lower (more negative) = better match. Visibility follows the same rules as `knowledge_read`.

### Docs (CHM)

Read and search CHM documentation files configured via `GABOS_CHM_FILES`.

| Tool          | Description                                                                                                                                                       |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docs_search` | Full-text search across configured CHM apps. Use for free-text queries.                                                                                           |
| `docs_read`   | Read the full Markdown content of a page. Requires `app`, `source`, and `page_path` (all from `docs_search` results). |

**Cache invalidation:**

The CHM cache is stored in `GABOS_CHM_CACHE_DIR` (default `~/.cache/gabos-mcp/chm`) with the layout `<cache_dir>/<app>/<source>/`. Deleting a subdirectory invalidates that cache and forces a rebuild on next access:

```bash
# Clear one source
rm -rf "$GABOS_CHM_CACHE_DIR/MYAPP/mysource"

# Clear one app
rm -rf "$GABOS_CHM_CACHE_DIR/MYAPP"

# Clear everything
rm -rf "$GABOS_CHM_CACHE_DIR"
```

The server detects external deletions and rebuilds automatically on next tool use — no restart required.

### Telemetry

Every tool call is logged to the logfmt file at `GABOS_TELEMETRY_LOG`. The admin tool provides a live dashboard.

| Tool               | Description                                                                                              |
| ------------------ | -------------------------------------------------------------------------------------------------------- |
| `telemetry_stats`  | Interactive dashboard: call counts by tool and user (bar charts), plus a sortable duration-stats table (min/max/mean/median/std per tool). Admin-only — requires `GABOS_ADMIN_USERS`. |

### Claude Code — Remote (OAuth)

```bash
claude mcp add --transport http gabos-mcp https://mcp.fuet.ch/mcp
```

On first use, Claude Code opens your browser to complete the GitHub OAuth flow. Tokens are stored locally and refreshed automatically.
