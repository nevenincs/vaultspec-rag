---
tags:
  - '#exec'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-17'
body_hash: 'sha256:43327afec6b2a5a71ddaa34aae01d0c18412531d3949a3f7928f598d2e2db852'
step_id: 'S04'
related:
  - "[[2026-07-16-mcp-stdio-lifetime-plan]]"
---

# Register the VAULTSPEC_RAG_STDIO_WATCHDOG env knob in the config env inventory following the existing knob conventions

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Register `STDIO_WATCHDOG = "VAULTSPEC_RAG_STDIO_WATCHDOG"` in the
  `EnvVar` enum with the kill-switch semantics comment.
- Point the watchdog module's `STDIO_WATCHDOG_ENV` at the enum member,
  honoring the no-bare-env-literals rule.

## Outcome

ruff, basedpyright, ty green.

## Notes

None.
