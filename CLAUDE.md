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
uv run fastmcp dev inspector src/gabos_mcp/server.py
```

## Architecture

Uses `src` layout with FastMCP 3.x. The four MCP primitives are **tools**, **resources**, **prompts**, and **context** (context is injected via `CurrentContext()`, not a standalone component).

```
src/gabos_mcp/
├── server.py          # FastMCP instance + wiring (imports and registers all components)
├── main.py            # Entrypoint — imports server, calls mcp.run()
├── tools/             # @mcp.tool functions, grouped by domain
├── extractors/        # Plain Python classes for non-trivial data fetching/parsing
├── resources/         # @mcp.resource functions (read-only data via URIs) — added as needed
└── prompts/           # @mcp.prompt templates — added as needed
```

**Key design principle:** Tools, resources, and prompts are thin glue — they validate input, call an extractor, and return results. The heavy logic lives in `extractors/`, which has no MCP dependency and is independently testable.

**Registration pattern:** Each tool module exposes a `register(mcp: FastMCP)` function that registers its tools on the given instance. `server.py` imports the module and calls `register(mcp)`. This avoids circular imports and works correctly with the FastMCP dev inspector.

## After Every Code Change

1. Update/add tests if necessary
2. Run tests: `uv run pytest`
3. Repeat until clean:
   1. `uv run ruff check .` — fix any lint errors
   2. `uv run ty check .` — fix any type errors
   3. `uv run ruff format .` — apply formatting
