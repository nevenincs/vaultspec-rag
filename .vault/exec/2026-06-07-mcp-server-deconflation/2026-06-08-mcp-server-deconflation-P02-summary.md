---
tags:
  - "#exec"
  - "#mcp-server-deconflation"
date: 2026-06-08
modified: '2026-06-08'
related:
  - "[[2026-06-07-mcp-server-deconflation-plan]]"
---

# mcp-server-deconflation P02 Summary

## Intent

Complete Phase P02: "Server/CLI Decoupling and Audit" to ensure the RAG service runs as a pure REST API decoupled from the MCP protocol.

## Actions Taken

- Refactored `src/vaultspec_rag/server/_main.py` to remove the FastMCP ASGI streamable HTTP transport mount completely.
- Refactored integration tests (`test_service_lifecycle.py` and `test_service_eviction.py`) to consume the new daemon REST endpoints instead of simulating MCP stdio requests over streamable HTTP.
- Re-routed all `list_projects_route` and `evict_project_route` administration endpoints directly through standard HTTP REST mapping.
- Corrected a JSON serialization crash with `Path` resolution in the daemon's snapshot response.
- Audited all CLI entrypoints and framework rules, migrating stale `server service` subcommands to their flattened names (`server start`, `server status`, `server jobs`, etc.).
- Renamed the MCP entrypoints inside `.vaultspec/rules/rules/vaultspec-rag.builtin.md` to point to `vaultspec_rag.mcp:main` and ran `vaultspec-core sync`.

## Outcome

The daemon is completely uncoupled from the MCP `FastMCP` framework logic. The CLI functions as a pure REST consumer. The test suite successfully passes without importing any MCP-specific transport dependencies, confirming total protocol deconflation. Phase P02 is complete.
