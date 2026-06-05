---
tags:
  - '#exec'
  - '#async-service-index'
date: '2026-06-04'
step_id: 'S12'
related:
  - "[[2026-06-04-async-service-index-plan]]"
---

# Refactor MCP tool handlers to act as thin transport delegates calling the new backend API

## Scope

- `src/vaultspec_rag/mcp_server/_tools.py`

## Description

- Refactor `reindex_vault` and `reindex_codebase` in `src/vaultspec_rag/mcp_server/_tools.py` to delegate the asynchronous task spawning and status tracking to the backend `jobs` module.
- Register a callback from the MCP server to increment and observe the Prometheus metrics upon job completion.
- Replace `src/vaultspec_rag/mcp_server/_jobs.py` with a simple redirection stub to delegate all queries to the backend.

## Outcome

- Refactored tool handlers and metrics successfully. All tests compile and run green.

## Notes
