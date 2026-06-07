---
tags:
  - '#research'
  - '#mcp-server-deconflation'
date: '2026-06-07'
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

## Next Steps

We must systematically split `mcp_server` into two distinct packages:

1. `vaultspec_rag.server`: The background HTTP daemon running FastAPI.
1. `vaultspec_rag.mcp`: The protocol adapter (stdio/SSE serialization, `@mcp.tool()` definitions).

Additionally, we need to collapse the `service` CLI group into the `server` group and correct all misleading docstrings.
