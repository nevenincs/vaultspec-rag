---
tags:
  - '#exec'
  - '#async-service-index'
date: '2026-06-04'
modified: '2026-07-27'
step_id: 'S12'
related:
  - "[[2026-06-04-async-service-index-plan]]"
---

## Description

### Scope

- `src/vaultspec_rag/mcp_server/_tools.py`

- Refactor `reindex_vault` and `reindex_codebase` in `src/vaultspec_rag/mcp_server/_tools.py` to delegate the asynchronous task spawning and status tracking to the backend `jobs` module.

- Register a callback from the MCP server to increment and observe the Prometheus metrics upon job completion.

- Replace `src/vaultspec_rag/mcp_server/_jobs.py` with a simple redirection stub to delegate all queries to the backend.

## Outcome

- Refactored tool handlers and metrics successfully. All tests compile and run green.

## Notes

No separate notes is recorded in the retained prior execution record. Source: retained prior execution record body.
