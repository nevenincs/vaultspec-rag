---
tags:
  - '#exec'
  - '#async-service-index'
date: '2026-06-04'
step_id: 'S17'
related:
  - "[[2026-06-04-async-service-index-plan]]"
---

# Refactor clean and status commands/tools in CLI and MCP to delegate to backend

## Scope

- `src/vaultspec_rag/cli/_status.py`
- `src/vaultspec_rag/cli/_index.py`
- `src/vaultspec_rag/mcp_server/_tools.py`

## Description

- Refactor `handle_status` and `handle_clean` in the CLI commands, as well as `get_index_status` in MCP tools, to delegate to `vaultspec_rag.get_status` and `vaultspec_rag.clean`.
- Remove manual database file operations, direct GPU/VRAM logic, and collection drops from CLI and MCP layers.

## Outcome

- Successfully refactored and verified status/clean operations.

## Notes
