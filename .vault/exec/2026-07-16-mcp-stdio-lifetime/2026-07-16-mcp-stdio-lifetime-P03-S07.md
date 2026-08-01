---
tags:
  - '#exec'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-17'
body_hash: 'sha256:05dad9215a939eba5e53208898c765d2c63b76569b7338d76d67623bcaf7bfef'
step_id: 'S07'
related:
  - "[[2026-07-16-mcp-stdio-lifetime-plan]]"
---

# Add ADR regression guards: fresh-interpreter import of the watchdog module loads neither torch nor mcp, and the HTTP daemon path never references the watchdog installer

## Scope

- `src/vaultspec_rag/tests/test_adr_regression.py`

## Description

- Add `TestStdioLifetimeWatchdogStaysThin` to the ADR regression suite:
  a fresh-interpreter import of the watchdog module must load neither
  `torch` nor `mcp`, and a source scan pins the installer to the stdio
  branch of `main` only (absent from the HTTP branch and `_lifespan`).

## Outcome

30 regression tests pass; ruff, basedpyright green.

## Notes

None.
