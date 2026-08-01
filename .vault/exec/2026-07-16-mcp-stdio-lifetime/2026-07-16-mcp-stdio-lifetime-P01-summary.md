---
tags:
  - '#exec'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-17'
body_hash: 'sha256:5ead81b60c498569342b35ed786bce18bbbb18d51b721f4b1414ef814b2471ec'
related:
  - "[[2026-07-16-mcp-stdio-lifetime-plan]]"
---

# `mcp-stdio-lifetime` `P01` summary

Both P01 Steps (S01, S02) are closed. The stdlib-only lifetime watchdog
module is complete.

- Created: `src/vaultspec_rag/server/_stdio_lifetime.py`

## Description

Delivered the watchdog core: fully-declared ctypes kernel32 bindings,
Toolhelp32 ancestor-chain discovery (bounded, cycle-safe, creation-time
monotonicity as the PID-reuse guard), immediate SYNCHRONIZE handle
acquisition, grace-window arming that prunes spawn-helper deaths, a
wait-any daemon watchdog thread, the structured stderr exit line with
`os._exit(0)`, the POSIX reparent-poll fallback, and the
`VAULTSPEC_RAG_STDIO_WATCHDOG` kill switch. Verified by ruff,
basedpyright, and ty on every commit; post-review hardening later closed
disarm-path handle leaks and moved the exit line to `json.dumps`.
