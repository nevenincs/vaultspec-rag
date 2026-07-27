---
tags:
  - '#exec'
  - '#async-service-index'
date: '2026-06-04'
modified: '2026-07-27'
step_id: 'S17'
related:
  - "[[2026-06-04-async-service-index-plan]]"
---

## Description

### Scope

- `src/vaultspec_rag/cli/_status.py`

- `src/vaultspec_rag/cli/_index.py`

- `src/vaultspec_rag/mcp_server/_tools.py`

- Refactor `handle_status` and `handle_clean` in the CLI commands, as well as `get_index_status` in MCP tools, to delegate to `vaultspec_rag.get_status` and `vaultspec_rag.clean`.

- Remove manual database file operations, direct GPU/VRAM logic, and collection drops from CLI and MCP layers.

## Outcome

- Successfully refactored and verified status/clean operations.

## Notes

No separate notes is recorded in the retained prior execution record. Source: retained prior execution record body.
