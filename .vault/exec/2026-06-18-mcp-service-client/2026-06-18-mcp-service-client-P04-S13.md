---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S13'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Correct the stale server-owns-mcp docstring in the server package init

## Scope

- `src/vaultspec_rag/server/__init__.py`

## Description

- Rewrote the module docstring so it stops claiming the server package owns the singleton `mcp` FastMCP instance; it now states the daemon exposes native REST only and the `mcp` instance lives solely in `vaultspec_rag.mcp._mcp`, served by the standalone stdio forwarder.
- Dropped the stale import-order step that described tool/resource/prompt decorator submodules registering against `mcp`, since the package no longer imports `_tools`, `_admin_tools`, or `_resources`.
- Removed the dead inline comment that labelled a now-absent decorator-registration import block.

## Outcome

The package init docstring and comments describe the post-split, post-thin-client reality: native REST daemon, no in-process MCP mount, MCP owned by the `mcp` package. Ruff and basedpyright pass clean on the file; no phantom `mcp start` reference was present.

## Notes

No behavior change: edits are confined to the module docstring and a dead comment block. The re-exported public surface and `__all__` were left untouched.
