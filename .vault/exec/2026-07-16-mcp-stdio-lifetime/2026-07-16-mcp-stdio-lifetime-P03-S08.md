---
tags:
  - '#exec'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-17'
step_id: 'S08'
related:
  - "[[2026-07-16-mcp-stdio-lifetime-plan]]"
---

# Document the stdio lifetime contract, the --parent-pid override, and the VAULTSPEC_RAG_STDIO_WATCHDOG knob in the service reference docs

## Scope

- `docs/`

## Description

- Add a "Stdio server lifetime" section to `docs/mcp.md` describing the
  self-reap contract, the stderr JSON exit line, exit code 0, and the
  two knobs (`--parent-pid`, `VAULTSPEC_RAG_STDIO_WATCHDOG=0`).
- Register the knob in the `docs/configuration.md` env table (new
  "Stdio MCP lifetime" section); mdformat pass applied (CI markdown
  gate).

## Outcome

Docs updated and mdformat-clean.

## Notes

None.
