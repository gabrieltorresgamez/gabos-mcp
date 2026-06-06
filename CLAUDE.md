# CLAUDE.md

A personal MCP server built with FastMCP 3.x. New tools, resources, prompts, and extractors are added over time.

## Architecture

**Key design principle:** Tools and prompts are thin glue — they validate input, call an extractor, and return results. Heavy logic lives in `extractors/`, which has no MCP dependency and is independently testable. Shared logic lives in `utils/`.

**Registration pattern:** Each tool module exposes a `register(mcp: FastMCP)` function. `server.py` imports and calls `register(mcp)`. This avoids circular imports and works with the FastMCP dev inspector.

**Tool naming convention:** Use `module_verb` so tools group alphabetically by module (e.g. `docs_search`, `knowledge_write`, `agent_context`). Never use `verb_module`.

**Suffix convention:** `_read`/`_search`/`_context` = read-only; `_write`/`_extract_learnings` = creates/modifies data; `_delete` = destructive.

## Agents

Agents do not call Claude themselves — `agent_context` assembles and returns context for the active session to use directly. Learning is opt-in via `agent_extract_learnings`, which calls `ctx.sample()` on the already-active session.

**Workflow:**
1. `agent_context(agent, query, folder_context?)` → `system_prompt` + `knowledge_catalogue` + optional `context_markdown`
2. `knowledge_read(id=...)` for catalogue entries relevant to the query
3. Answer using `system_prompt` as persona and fetched knowledge
4. Optionally `agent_extract_learnings(agent, query, answer, referenced_chm_pages?)` to persist learnings

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

## After Every Code Change

1. Update/add tests if necessary
2. `uv run pytest`
3. Repeat until clean: `uv run ruff check .` → `uv run ty check .` → `uv run ruff format .`
4. Update `CLAUDE.md` and `README.md` if the change affects architecture, commands, or configuration
