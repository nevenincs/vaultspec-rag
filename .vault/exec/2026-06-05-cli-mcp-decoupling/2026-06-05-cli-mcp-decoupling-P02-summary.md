---
tags:
  - '#exec'
  - '#cli-mcp-decoupling'
date: '2026-06-05'
related:
  - '[[2026-06-05-cli-mcp-decoupling-plan]]'
  - '[[2026-06-05-cli-mcp-decoupling-adr]]'
---

# `cli-mcp-decoupling` `P02` summary

Phase P02 refactors the MCP server admin tools to delegate to standardized backend facade APIs and introduces benchmark and quality tool parity to the MCP server.

- Modified: `src/vaultspec_rag/mcp_server/_admin_tools.py` (updated `get_service_state`, added `benchmark` and `quality` tools)
- Closed Step: `P02.S05` (`.vault/exec/2026-06-05-cli-mcp-decoupling/2026-06-05-cli-mcp-decoupling-P02-S05.md`)
- Closed Step: `P02.S06` (`.vault/exec/2026-06-05-cli-mcp-decoupling/2026-06-05-cli-mcp-decoupling-P02-S06.md`)

## Description

The `get_service_state` MCP tool was refactored to delegate entirely to the newly added `vaultspec_rag.get_service_state` backend facade, which unifies data aggregation from RAG status, registry snapshots, and file watcher configuration.

Additionally, two new MCP tools were registered:

- `benchmark`: triggers the backend `run_benchmark` facade to run timing probes and return latency statistics and resource usage metrics.
- `quality`: triggers the backend `run_quality_probe` facade to execute needle precision probes over a temporary workspace and return passing score breakdowns.

These tool calls run in threadpools (via `_run_in_thread`) to prevent blocking the async event loop during execution.

## Tests

Verification commands:

- `uv run ruff check src/vaultspec_rag/` - all checks passed.
- `uv run pytest -m unit` - all unit tests passed.
