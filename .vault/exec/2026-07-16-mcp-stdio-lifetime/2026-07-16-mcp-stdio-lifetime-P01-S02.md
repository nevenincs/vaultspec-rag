---
tags:
  - '#exec'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-17'
step_id: 'S02'
related:
  - "[[2026-07-16-mcp-stdio-lifetime-plan]]"
---

# Add watchdog arming in the same module: startup grace window that prunes ancestors dead during grace, wait-any watchdog daemon thread, structured stderr line naming the dead ancestor, os._exit(0) trigger, POSIX getppid reparent poll fallback, and the VAULTSPEC_RAG_STDIO_WATCHDOG disable knob

## Scope

- `src/vaultspec_rag/server/_stdio_lifetime.py`

## Description

- Add `_windows_watchdog`: sleep the grace window, prune ancestors that
  died during grace (closing their handles), wait-any
  `WaitForMultipleObjects` on the survivors, disarm with a logged error on
  wait failure instead of killing a live session.
- Add `_exit_on_ancestor_death`: one structured JSON line to stderr naming
  the dead ancestor, then `os._exit(0)` (exit 0 - self-reap is intended,
  not a crash for brokers to retry).
- Add `_posix_watchdog` (coarse `os.getppid()` reparent poll plus explicit
  extra-pid liveness) and `_pid_alive` with logged unexpected errors.
- Add `install_stdio_lifetime_watchdog(parent_pid)`: never raises, honors
  the `VAULTSPEC_RAG_STDIO_WATCHDOG` disable knob, arms the daemon thread
  and logs the watched ancestor set.

## Outcome

Module complete; ruff check/format, basedpyright, and ty all pass.

## Notes

`os._exit` is load-bearing per research S2 (the anyio stdin reader cannot
be cancelled in-process); a `WaitForMultipleObjects` result outside the
signaled range disarms rather than exits, biasing false-negatives over
killing live sessions.
