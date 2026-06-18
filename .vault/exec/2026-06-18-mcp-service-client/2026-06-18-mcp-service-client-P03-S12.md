---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-18'
step_id: 'S12'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Remove the in-process GPU model load from the stdio branch and make stdio the sole MCP transport in the entry point

## Scope

- `src/vaultspec_rag/server/_main.py`

## Description

- Removed the eager in-process GPU model load from the stdio branch of the server entry point: the stdio MCP process no longer calls the registry's `load_model`, so it loads no Torch and holds no GPU resource.
- Moved the guarded `mcp` import into the stdio branch only, so it runs on the single path that actually needs the MCP protocol package, and preserved the actionable `ImportError` message covering both a missing `mcp` and a broken Windows pywin32 link.
- Kept the stdio watcher-cleanup wiring (`_on_close_project`, `_stop_all_watchers`, `close_all`) and `mcp.run(transport="stdio")` so stdio remains a working thin transport.
- Added a source-inspection test asserting the entry point no longer calls `load_model`, and reworded the docstrings to state that stdio is the sole MCP transport and delegates every tool to the daemon over HTTP.

## Outcome

stdio is now the sole MCP transport, and the stdio process is a thin forwarder: it serves MCP over stdio, loads no model, and reaches the running daemon over HTTP through the service client for every tool. The agent registration launches `vaultspec-search-mcp` with no port, taking exactly this branch, so the single worst prior regression (the stdio process paying the full GPU model-load cost it never used) is eliminated. The guarded import error stays on the path that needs it, and the `mcp` package remains a declared core dependency. Server and import-isolation tests pass, ruff is clean, and basedpyright reports zero errors for the server package.

## Notes

Import-guard decision: the `from ..mcp import mcp` import lives in the stdio branch only. With the daemon mount removed, the HTTP service backend has no use for the MCP package, so scoping the import to the stdio path keeps the daemon free of the dependency while preserving the pywin32/missing-dep guidance exactly where a failure would surface. The model-load removal also keeps the stdio entry consistent with the import-isolation contract that the MCP layer loads no heavy libraries. Updating the server tests that bound the removed mount, wrapper, and model-load expectations overlaps the later test-update step; it was done here so the suite stays green within this phase.
