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
uv run pytest tests/test_tools/test_example.py

# Run a single test
uv run pytest tests/test_tools/test_example.py::test_name

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
│   ├── agents.py      # agent_* tools: CRUD + context + learn + doc refs
│   ├── chm.py         # docs_* tools: CHM documentation search/read
│   └── knowledge.py   # knowledge_* tools: shared knowledge store
├── extractors/        # Plain Python classes for non-trivial data fetching/parsing
│   ├── agent_store.py # AgentStore: SQLite (agents + agent_doc_refs tables)
│   ├── agent_assembler.py # AgentAssembler: context assembly + ctx.sample() learning loop
│   ├── chm.py         # ChmExtractor: CHM file processing pipeline
│   └── knowledge.py   # KnowledgeStore: SQLite-backed with FTS5 search
├── utils/             # Shared utilities (no MCP dependency) reused across extractors
│   ├── auth.py        # GitHub OAuth helpers
│   ├── search.py      # SearchIndex (SQLite FTS5) — used by ChmExtractor
│   └── stores.py      # get_knowledge_store() / get_agent_store() factory helpers
├── resources/         # @mcp.resource functions (read-only data via URIs) — added as needed
└── prompts/           # @mcp.prompt templates — added as needed
```

**Key design principle:** Tools, resources, and prompts are thin glue — they validate input, call an extractor, and return results. The heavy logic lives in `extractors/`, which has no MCP dependency and is independently testable. Shared logic that multiple extractors need lives in `utils/`.

**Registration pattern:** Each tool module exposes a `register(mcp: FastMCP)` function that registers its tools on the given instance. `server.py` imports the module and calls `register(mcp)`. This avoids circular imports and works correctly with the FastMCP dev inspector.

**Tool naming convention:** Use `module_verb` or `module_verb_noun` so tools group alphabetically by module. Examples: `docs_search`, `docs_read_page`, `knowledge_add`, `knowledge_list`, `agent_context`, `agent_doc_ref_add`. Never use `verb_module` or `verb_module_noun`.

## Agents

Agents are multipurpose domain experts stored in the database (`agents.db`). Each agent has:
- A system prompt (persona + response format)
- A list of knowledge tags to auto-inject as context
- A model setting and `auto_learn` flag

**Agent tools:** `agent_create`, `agent_get`, `agent_list`, `agent_update`, `agent_delete`, `agent_context`, `agent_learn`, `agent_extract_learnings`, `agent_doc_ref_add`, `agent_doc_ref_list`, `agent_doc_ref_delete`

**No external API key required.** Agents do not call Claude themselves — `agent_context` assembles and returns the context (system prompt + relevant knowledge + CHM doc pages) for the active Claude session to use directly. Learning is opt-in via `agent_extract_learnings`, which calls `ctx.sample()` on the already-active session.

**Workflow:**
1. Call `agent_context(agent, query, folder_context?)` → get `system_prompt` + `context_markdown`
2. Use `system_prompt` as persona and `context_markdown` as injected knowledge to answer the query
3. Optionally call `agent_extract_learnings(agent, query, answer, referenced_chm_pages?)` to persist what was learned

**Permissions:** Only the agent's owner can update, delete it, or modify its doc refs. Any authenticated user can read agents and retrieve context.

**Knowledge tag convention:**
- `agent:<name>` — global knowledge for this agent
- `agent:<name>:folder:<key>` — folder/context-specific knowledge

**Environment variables:**
- `GABOS_AGENTS_DB` — path to agents SQLite DB (default: `~/.local/share/gabos-mcp/agents.db`)

## After Every Code Change

1. Update/add tests if necessary
2. Run tests: `uv run pytest`
3. Repeat until clean:
   1. `uv run ruff check .` — fix any lint errors
   2. `uv run ty check .` — fix any type errors
   3. `uv run ruff format .` — apply formatting
4. Update `CLAUDE.md` and `README.md` if the change affects architecture, commands, or configuration
