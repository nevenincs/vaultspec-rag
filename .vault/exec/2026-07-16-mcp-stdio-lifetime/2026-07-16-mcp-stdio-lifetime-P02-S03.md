---
tags:
  - '#exec'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-17'
step_id: 'S03'
related:
  - "[[2026-07-16-mcp-stdio-lifetime-plan]]"
---

# Wire install_stdio_lifetime_watchdog into the stdio branch before mcp.run, add the optional --parent-pid argument, and keep HTTP daemon mode and --help paths watchdog-free

## Scope

- `src/vaultspec_rag/server/_main.py`

## Description

- Add the optional `--parent-pid` argument to the console-script argparse
  surface (stdio-only semantics documented in the help text).
- Install the watchdog in the stdio branch before `mcp.run`, with the
  stdio-only rationale stated at the call site; HTTP daemon mode and
  `--help` never reach the installer.

## Outcome

ruff, basedpyright, ty green; `vaultspec-search-mcp --help` still exits 0
without arming anything (packaging smoke contract preserved).

## Notes

None.
