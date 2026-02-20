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
uv run ruff check src/

# Type check
uv run ty check src/
```

## Architecture

Uses `src` layout with FastMCP 3.x. The four MCP primitives are **tools**, **resources**, **prompts**, and **context** (context is injected via `CurrentContext()`, not a standalone component).

```
src/gabos_mcp/
├── server.py          # FastMCP instance + wiring (imports all component modules)
├── main.py            # Entrypoint — imports server, calls mcp.run()
├── tools/             # @mcp.tool functions, grouped by domain
├── resources/         # @mcp.resource functions (read-only data via URIs)
├── prompts/           # @mcp.prompt templates
└── extractors/        # Plain Python classes for non-trivial data fetching/parsing
```

**Key design principle:** Tools, resources, and prompts are thin glue — they validate input, call an extractor, and return results. The heavy logic lives in `extractors/`, which has no MCP dependency and is independently testable.

`server.py` creates the `FastMCP("gabos-mcp")` instance and is where all component modules get imported/registered. `main.py` stays minimal.
