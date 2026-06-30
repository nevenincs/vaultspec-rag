---
tags:
  - '#exec'
  - '#mcp-optional-dependency'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S04'
related:
  - "[[2026-06-30-mcp-optional-dependency-plan]]"
---

# Add a regression test asserting importing vaultspec_rag and the CLI loads no mcp or pywin32

## Scope

- `src/vaultspec_rag/tests/test_cli_no_mcp_import.py`

## Description

Added the CLI-path-is-mcp-free regression test.

## Outcome

`test_cli_no_mcp_import.py` runs a fresh subprocess that imports `vaultspec_rag` and the CLI app and asserts no `mcp`/`win32*`/`pywintypes`/`pythoncom` module loaded, so a future eager import on the CLI path fails the build (MO4).

## Notes

Passes; ruff/ty green.
