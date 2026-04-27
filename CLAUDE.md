# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A personal MCP (Model Context Protocol) server built with FastMCP 3.x. It's an evolving project — new tools, resources, prompts, and extractors are added over time.

## Commands

```bash
# Run the server
uv run gabos-mcp

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_tools/test_agents.py

# Run a single test
uv run pytest tests/test_tools/test_agents.py::TestAgentRead::test_fetch_by_name

# Lint
uv run ruff check .

# Format
uv run ruff format .

# Type check
uv run ty check .

# Dev inspector (interactive tool testing in browser)
uv run fastmcp dev inspector src/gabos_mcp/server.py --with-editable .
```

## Architecture

Uses `src` layout with FastMCP 3.x. The four MCP primitives are **tools**, **resources**, **prompts**, and **context** (context is injected via `CurrentContext()`, not a standalone component).

```
src/gabos_mcp/
├── server.py          # FastMCP instance + wiring (imports and registers all components)
├── main.py            # Entrypoint — selects transport via env vars, runs server
├── tools/             # @mcp.tool functions, grouped by domain
│   ├── agents.py      # agent_* tools: read + context + extract_learnings + write + delete
│   ├── chm.py         # docs_* tools: search + polymorphic read
│   └── knowledge.py   # knowledge_* tools: read + write + delete
├── extractors/        # Plain Python classes for non-trivial data fetching/parsing
│   ├── agent_store.py # AgentStore: SQLite (agents + agent_doc_refs tables)
│   ├── agent_assembler.py # AgentAssembler: context assembly + ctx.sample() learning loop
│   ├── chm.py         # ChmExtractor: CHM file processing pipeline
│   └── knowledge.py   # KnowledgeStore: SQLite-backed with FTS5 search
├── utils/             # Shared utilities (no MCP dependency) reused across extractors
│   ├── auth.py        # GitHub OAuth helpers
│   ├── search.py      # SearchIndex (SQLite FTS5) — used by ChmExtractor
│   └── stores.py      # get_knowledge_store() / get_agent_store() factory helpers
└── prompts/           # @mcp.prompt templates — added as needed
```

**Key design principle:** Tools and prompts are thin glue — they validate input, call an extractor, and return results. The heavy logic lives in `extractors/`, which has no MCP dependency and is independently testable. Shared logic that multiple extractors need lives in `utils/`.

**Registration pattern:** Each tool module exposes a `register(mcp: FastMCP)` function that registers its tools on the given instance. `server.py` imports the module and calls `register(mcp)`. This avoids circular imports and works correctly with the FastMCP dev inspector.

**Tool naming convention:** Use `module_verb` so tools group alphabetically by module. Examples: `docs_search`, `docs_read`, `knowledge_read`, `knowledge_write`, `agent_context`, `agent_write`. Never use `verb_module`.

## Tools (10 total)

Suffix convention: `_read`/`_search`/`_context` = read-only; `_write`/`_extract_learnings` = creates/modifies data; `_delete` = destructive.

| Tool                      | Side effect | Description                                                                                       |
| ------------------------- | ----------- | ------------------------------------------------------------------------------------------------- |
| `agent_read`              | read        | List visible agents or fetch one by name/ID (with optional doc refs)                              |
| `agent_context`           | read        | Assemble system prompt + knowledge + CHM context for a query                                      |
| `agent_extract_learnings` | write       | Extract and persist learnings from a Q&A via `ctx.sample()`                                       |
| `agent_write`             | write       | Create or update an agent; accepts `doc_refs` and `learnings` fields                              |
| `agent_delete`            | delete      | Delete an agent, or remove specific doc refs by ID                                                |
| `knowledge_read`          | read        | Fetch a single knowledge entry by ID or list entries                                              |
| `knowledge_write`         | write       | Create or update a knowledge entry                                                                |
| `knowledge_delete`        | delete      | Delete a knowledge entry (owner only)                                                             |
| `docs_search`             | read        | Full-text search across CHM docs                                                                  |
| `docs_read`               | read        | Browse or read CHM docs (no args → apps; app → sources; app+source → pages; +page_path → content) |

## Agents

Agents are multipurpose domain experts stored in the database (`agents.db`). Each agent has:
- A system prompt (persona + response format)
- A list of knowledge tags to auto-inject as context
- A model setting and `auto_learn` flag

**No external API key required.** Agents do not call Claude themselves — `agent_context` assembles and returns the context (system prompt + relevant knowledge + CHM doc pages) for the active Claude session to use directly. Learning is opt-in via `agent_extract_learnings`, which calls `ctx.sample()` on the already-active session.

**Workflow:**
1. Call `agent_context(agent, query, folder_context?)` → get `system_prompt` + `context_markdown`
2. Use `system_prompt` as persona and `context_markdown` as injected knowledge to answer the query
3. Optionally call `agent_extract_learnings(agent, query, answer, referenced_chm_pages?)` to persist what was learned

**Permission model:** Owner-only writes and deletes. Reads open to all authenticated users; private items hidden from non-owners.

**Agent-tag ownership check (`_assert_agent_tags_owned`):** Any knowledge entry that uses a tag of the form `agent:<name>` or `agent:<name>:folder:<key>` requires the caller to own that agent. This is enforced in `knowledge_write` and resolved in bulk via `AgentStore.get_many()`.

**Knowledge tag convention:**
- `agent:<name>` — global knowledge for this agent
- `agent:<name>:folder:<key>` — folder/context-specific knowledge

**Environment variables:**
- `GABOS_AGENTS_DB` — path to agents SQLite DB (default: `~/.local/share/gabos-mcp/agents.db`)
- `GABOS_KNOWLEDGE_DB` — path to knowledge SQLite DB (default: `~/.local/share/gabos-mcp/knowledge.db`)
- `GABOS_CHM_CACHE_DIR` — CHM cache directory (default: `~/.cache/gabos-mcp/chm`); delete subdirs to invalidate
- `GABOS_BACKUP_DIR` — backup folder (backups disabled when unset)
- `GABOS_BACKUP_TIME` — daily backup time in 24h format (default: `02:00`)
- `GABOS_BACKUP_RETENTION_DAYS` — days to keep backups, 0 = forever (default: `30`)

## After Every Code Change

1. Update/add tests if necessary
2. Run tests: `uv run pytest`
3. Repeat until clean:
   1. `uv run ruff check .` — fix any lint errors
   2. `uv run ty check .` — fix any type errors
   3. `uv run ruff format .` — apply formatting
4. Update `CLAUDE.md` and `README.md` if the change affects architecture, commands, or configuration
