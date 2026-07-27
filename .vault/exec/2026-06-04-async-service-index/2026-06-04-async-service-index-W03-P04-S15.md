---
tags:
  - '#exec'
  - '#async-service-index'
date: '2026-06-04'
modified: '2026-07-27'
step_id: 'S15'
related:
  - "[[2026-06-04-async-service-index-plan]]"
---

## Description

### Scope

- `src/vaultspec_rag/mcp_server/_tools.py`

- Refactor `search_vault` and `search_codebase` MCP tool handlers inside `src/vaultspec_rag/mcp_server/_tools.py` to call the public backend API functions `vaultspec_rag.search_vault` and `vaultspec_rag.search_codebase` rather than leasing slots and executing searches directly.

- Convert MCP handlers to act strictly as thin transport delegates.

## Outcome

- Successfully refactored MCP search tool handlers and verified that they delegate logic cleanly to the backend APIs.

## Notes

No separate notes is recorded in the retained prior execution record. Source: retained prior execution record body.
