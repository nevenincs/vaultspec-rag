---
tags:
  - '#exec'
  - '#stdio-watchdog-convergence'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S01'
related:
  - "[[2026-07-17-stdio-watchdog-convergence-plan]]"
---

# Add resolve_stdin_client_pid (GetNamedPipeServerProcessId on the inherited stdin handle, fail-open) and the grace_prunable flag on watched targets

## Scope

- `src/vaultspec_rag/server/_stdio_lifetime.py`

## Description

- Bind `GetNamedPipeServerProcessId` (full argtypes/restype) and add
  `resolve_stdin_client_pid`: msvcrt stdin handle to pipe-creator PID,
  failing open for console/redirected stdin, zero/self PIDs, and any
  unexpected error.
- Add `grace_prunable` to `WatchedAncestor` (default True) and the
  `open_watched` helper for precise single-PID anchors.

## Outcome

ruff/basedpyright/ty green.

## Notes

None.
