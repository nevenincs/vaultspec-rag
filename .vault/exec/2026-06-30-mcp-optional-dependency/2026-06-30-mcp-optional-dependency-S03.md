---
tags:
  - '#exec'
  - '#mcp-optional-dependency'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S03'
related:
  - "[[2026-06-30-mcp-optional-dependency-plan]]"
---

# Retarget the MCP-entry-point ImportError guard message at the vaultspec-rag[mcp] extra

## Scope

- `src/vaultspec_rag/server/_main.py`

## Description

Retargeted the MCP entry-point ImportError guard at the [mcp] extra.

## Outcome

`server/_main.py`'s guarded `from ..mcp import mcp` now tells the user to `uv add vaultspec-rag[mcp]` (or `uv sync --extra mcp`), keeping the pywin32-postinstall hint for the installed-but-broken case (MO3).

## Notes

The daemon path is unchanged - it still never imports mcp.
