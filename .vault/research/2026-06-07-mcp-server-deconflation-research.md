---
tags:
  - '#research'
  - '#mcp-server-deconflation'
date: '2026-06-07'
modified: '2026-06-30'
related: []
---

# `mcp-server-deconflation` research: `Blast Radius of MCP and Server Conflation`

## Background

The project currently conflates the general "RAG Service / Server" (the background HTTP daemon running FastAPI, managing Qdrant, coordinating file watchers, and executing background index jobs) with the "MCP Server" (the protocol adapter that communicates over stdio/SSE to expose RAG capabilities to LLM clients). This conceptual and architectural leak causes significant cognitive overhead and violates boundary separation.

## Blast Radius Findings

Based on an audit of the codebase, the terminology conflation extends deeply into several modules:

1. **Module Names & Entrypoints (Architectural Violations):**

   - **`vaultspec_rag/mcp_server/`**: The entire subpackage is named `mcp_server`, yet it contains general background service files completely unrelated to the Model Context Protocol, including:
     - `_routes.py`: General REST endpoints (`/health`, `/logs`, `/jobs`, `/projects`, `/metrics`).
     - `_lifespan.py`: General app lifespan, model initialization, and registry slot lifespans.
     - `_watcher.py`: General file watching daemon logic.
     - `_state.py`: Global HTTP state configuration.
   - **`vaultspec_rag/cli/_process.py`**: The CLI daemon spawns the HTTP/FastAPI service using `python -m vaultspec_rag.mcp_server --port N`.

1. **CLI Command Hierarchy Conflation:**

   - **`vaultspec_rag/cli/_app.py`**: The CLI groups `server service` and `server mcp` together under the `server` group. Operators must type deeply nested commands like `vaultspec-rag server service start` to manage the resident daemon, creating redundant nesting.

1. **CLI Help Strings & Docstrings:**

   - **`_service_lifecycle.py`**: The help text for `service_start` incorrectly states "Spawns the MCP server on the given port", when it actually spawns the HTTP REST RAG service.
   - **`_index.py`**: The `index` CLI command help text incorrectly claims that `--port` delegates "to a running MCP server", when it actually talks to the HTTP REST service.

1. **Test Suite & Framework Rules:**

   - **`tests/test_mcp_server.py`**: Extensive unit tests tightly coupled to the package name and internal module structure.
   - **`tests/`**: Other daemon integration tests that refer to the `mcp_server` internal objects.
   - **`.vaultspec/rules/vaultspec-rag.builtin.md`**: The framework's core rules specifically document the entry point as `vaultspec_rag.mcp_server:main`, which needs to be updated.

1. **Architectural Conflation (Daemon as MCP Server):**

   - **`vaultspec_rag/cli/_mcp_search.py`**: The CLI's fast-path (`_try_mcp_search` and `_try_mcp_reindex`) currently connects to the daemon using the `mcp.client.streamable_http` module. This means the daemon acts directly as an MCP server via SSE, forcing the daemon to handle protocol parsing instead of exposing native REST APIs for core RAG operations.
   - **`vaultspec_rag/mcp_server/_tools.py`**: The MCP tools execute `vaultspec_rag` logic in-process. If `vaultspec-search-mcp` is run as a standalone stdio adapter, it runs its own RAG instance rather than acting as a lightweight client delegating to the resident daemon.

## Next Steps

To properly decouple the "RAG Server" from the "MCP Server", we must execute a deep architectural refactor:

1. **Native REST APIs**: The background HTTP daemon (`vaultspec_rag.server`) must expose native REST endpoints for `/search` and `/reindex`, completely dropping its reliance on hosting an MCP SSE endpoint.
1. **CLI as a REST Client**: The CLI fast-path (`_try_mcp_search`) must be rewritten to consume these new REST endpoints via standard HTTP requests (`_try_http_search`).
1. **MCP as a Consumer Client**: The MCP protocol adapter (`vaultspec_rag.mcp`) must be isolated as a standalone, lightweight wrapper that proxies LLM requests to the daemon's REST API, stripping it of all in-process RAG orchestration.
1. **Package & CLI Separation**: Rename `mcp_server` to `server`, flatten the CLI `server service` group to `server`, and decouple the `mcp` startup commands. Correct all misleading docstrings and references in the test suite and framework rules.
