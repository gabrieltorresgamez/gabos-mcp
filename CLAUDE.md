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

**`knowledge_tags`** — optional list of *extra* tag scopes searched in addition to
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

## Environment Variables

- `GABOS_AGENTS_DB` — agents SQLite DB path (default: `~/.local/share/gabos-mcp/agents.db`)
- `GABOS_KNOWLEDGE_DB` — knowledge SQLite DB path (default: `~/.local/share/gabos-mcp/knowledge.db`)
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
