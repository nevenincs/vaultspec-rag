---
tags:
  - '#exec'
  - '#cli-mcp-decoupling'
date: '2026-06-05'
modified: '2026-07-27'
step_id: 'S06'
related:
  - "[[2026-06-05-cli-mcp-decoupling-plan]]"
---

## Description

### Scope

- `src/vaultspec_rag/mcp_server/_admin_tools.py`

- Refactor `get_service_state` tool in `_admin_tools.py` to call the backend `get_service_state` facade.
- Add `benchmark` tool to the MCP server calling the backend `run_benchmark` facade.
- Add `quality` tool to the MCP server calling the backend `run_quality_probe` facade.

## Outcome

- The MCP server now has full feature parity with the CLI for benchmark and quality commands, and all three delegate directly to backend APIs.

## Notes

No separate notes is recorded in the retained prior execution record. Source: retained prior execution record body.
