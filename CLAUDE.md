# CLAUDE.md

A personal MCP server built with FastMCP 3.x. New tools, resources, prompts, and extractors are added over time.

## Architecture

**Key design principle:** Tools and prompts are thin glue — they validate input, call an extractor, and return results. Heavy logic lives in `extractors/`, which has no MCP dependency and is independently testable. Shared logic lives in `utils/`.

**Registration pattern:** Each tool module exposes a `register(mcp: FastMCP)` function. `server.py` imports and calls `register(mcp)`. This avoids circular imports and works with the FastMCP dev inspector.

**Tool naming convention:** Use `module_verb` so tools group alphabetically by module (e.g. `docs_search`, `knowledge_write`, `agent_read`). Never use `verb_module`.

**Suffix convention:** `_read`/`_search` = read-only; `_write` = creates/modifies data; `_delete` = destructive.

**Telemetry:** `TelemetryMiddleware` (`utils/telemetry.py`) records every tool call anonymously (tool name, duration, success/error) to the logfmt log at `GABOS_TELEMETRY_LOG`. No caller identity is recorded.

## Agents

Agents are domain expert personas stored in the database. Context assembly is fully manual — the model retrieves what it needs, rather than having context force-fed to it.

**Workflow:**

1. `agent_search()` → pick agent, note `id` and `name`
2. `agent_read(id=...)` → `system_prompt`, `knowledge_tags`
3. Search the agent's knowledge. Always search the `agent:<name>` baseline:
   `knowledge_search(query=..., tag="agent:<name>")`. If `knowledge_tags` is
   non-empty, run one additional `knowledge_search` per listed tag and merge
   the results. Most agents leave `knowledge_tags` empty and rely on the
   baseline alone.
4. `knowledge_read(id=...)` for entries worth reading
5. `docs_search` / `docs_read` if CHM documentation is relevant
6. Answer using `system_prompt` as persona
7. `knowledge_write(tags=["agent:<name>"])` to persist new facts

**`knowledge_tags`** — optional list of _extra_ tag scopes searched in addition to
the agent's own `agent:<name>` namespace. Use it when an agent should also draw
on shared or cross-domain knowledge (e.g. `agent:common`). Empty is the normal
case — the agent then searches only `agent:<name>`. The `agent:<name>` baseline
is always searched regardless of this field, so this can only broaden scope,
never hide the agent's own knowledge.

**Permission model:** Owner-only writes and deletes. Reads open to all authenticated users; private items hidden from non-owners.

**Agent-tag ownership check (`_assert_agent_tags_owned`):** Any knowledge entry tagged `agent:<name>` or `agent:<name>:folder:<key>` requires the caller to own that agent. Enforced in `knowledge_write`, resolved via `AgentStore.get_many()`.

**Knowledge tag convention:**

- `agent:<name>` — global knowledge for this agent
- `agent:<name>:folder:<key>` — folder/context-specific knowledge

## Schema (ground truth)

`SchemaStore` (`extractors/schema.py`) is a Tier-1 ground-truth complement to `knowledge_*`:
objective, auto-refreshed facts pulled straight from an OMNITRACKER Export Documentation XML,
rather than hand-maintained prose. Upload goes through `fastmcp.apps.FileUpload`
(`utils/uploads.py`'s `SchemaFileUpload`, wired into `server.py` via `mcp.add_provider`) so the raw
XML never enters the model's context window; `schema_write` reads it server-side, parses/validates
it (`extractors/schema_xml.py`, pure — no MCP dependency), upserts the normalized result, and deletes
the raw upload once parsing has been attempted (success or failure — the `finally` around
`parse_export` guarantees cleanup even on an unexpected exception). No history table — each import
fully replaces the row for a given key.

Two tables, both upserted, both FTS5-indexed (trigram, matching the knowledge store's pattern):
`schema_folders` (one row per folder alias, holding all of that folder's own object groups) and
`schema_globals` (one row per Global Object, keyed by `(environment, group_type, object_name)`).
`environment` is passed explicitly to `schema_write` — no auto-detection from the export's `Head`
block — but it's checked against `utils/environments.validate_environment`: blank names are always
rejected, and if `GABOS_SCHEMA_ENVIRONMENTS` (a plain comma-separated allowlist, not a host mapping)
is configured, unlisted names are rejected too, catching typos before they create a stray environment
bucket. `schema_write` is gated by a separate admin allowlist (`GABOS_SCHEMA_ADMINS`, checked via
`utils/auth.is_schema_admin`), distinct from the server-access allowlist — an admin must be in both.

**Verbosity:** `extractors/schema_xml.py` prunes empty/null keys from every normalized object
(`_prune_empty`) and collapses single-item `Enabled`/`Mandatory`/`Default value` rule wrappers down
to their scalar `Rule` text (`_flatten_rule` — the wrapper array is kept only when a field has
genuinely conditional, multi-item rules). `schema_read` defaults to a cheap summary (category name →
entry count) and only returns full per-object detail when the caller passes `categories` (e.g.
`categories=["Fields"]`) — this is a breaking change from the old behavior of always returning the
full folder dump. All four schema read tools (`schema_read`, `schema_globals_read`,
`schema_diff_read`, `schema_search`) also take a `format` param (`"yaml"` | `"json"`, default
`"yaml"`) — pure serialization-layer change via `utils/serialization.dump_response`, same underlying
data either way. This changes the default output format from JSON to YAML; callers with existing
JSON parsers must pass `format="json"` explicitly to preserve the old behavior.

## Environment Variables

- `GABOS_AGENTS_DB` — agents SQLite DB path (default: `~/.local/share/gabos-mcp/agents.db`)
- `GABOS_KNOWLEDGE_DB` — knowledge SQLite DB path (default: `~/.local/share/gabos-mcp/knowledge.db`)
- `GABOS_SCHEMA_DB` — schema SQLite DB path (default: `~/.local/share/gabos-mcp/schema.db`)
- `GABOS_SCHEMA_ENVIRONMENTS` — comma-separated allowlist of valid environment names for `schema_write` (default: unset, any non-blank name accepted)
- `GABOS_SCHEMA_ADMINS` — comma-separated GitHub logins allowed to run `schema_write` (default: none)
- `GABOS_CHM_CACHE_DIR` — CHM cache dir (default: `~/.cache/gabos-mcp/chm`); delete subdirs to invalidate
- `GABOS_BACKUP_DIR` — backup folder (backups disabled when unset)
- `GABOS_BACKUP_TIME` — daily backup time 24h format (default: `02:00`)
- `GABOS_BACKUP_RETENTION_DAYS` — days to keep backups, 0 = forever (default: `30`)
- `GABOS_TELEMETRY_LOG` — anonymous logfmt tool-call log path (default: `~/.local/share/logs/gabos-mcp/tool_calls.log`)

## After Every Code Change

1. Update/add tests if necessary
2. `uv run pytest`
3. Repeat until clean: `uv run ruff check .` → `uv run ty check .` → `uv run ruff format .`
4. Update `CLAUDE.md` and `README.md` if the change affects architecture, commands, or configuration
