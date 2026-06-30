---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S14'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Correct the stale server-owns-mcp docstring in the server state module

## Scope

- `src/vaultspec_rag/server/_state.py`

## Description

- Corrected the state module docstring so it no longer calls the module the canonical home of the singleton `mcp` FastMCP instance; it now describes the module as the home of the daemon's process-wide globals and states the `FastMCP` instance lives only in `vaultspec_rag.mcp._mcp`, served by the standalone stdio forwarder.
- Updated the rebind-discipline bullet to drop `mcp` from the list of in-place-mutated names, since the module no longer defines or registers against it; the watcher bookkeeping names remain.

## Outcome

The docstring matches the code: the module defines only daemon globals (registry, watcher dicts, identity token, HTTP-mode flag, metrics holders) and no `mcp` symbol. Confirmed no `mcp` or `FastMCP` reference survives outside the corrected prose. Ruff and basedpyright pass clean.

## Notes

No behavior change: edits are confined to the module docstring. No code symbol was added or removed.
