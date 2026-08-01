---
tags:
  - '#exec'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-17'
body_hash: 'sha256:42f3fe07df21dae14fbc98e59c0e6549069acb467e3a3415386e310da9cb8429'
step_id: 'S05'
related:
  - "[[2026-07-16-mcp-stdio-lifetime-plan]]"
---

# Add unit tests for ancestor discovery guards, disable knob, parent-pid override handling, and non-stdio inertness

## Scope

- `src/vaultspec_rag/tests/test_stdio_lifetime.py`

## Description

- Add `test_stdio_lifetime.py` unit coverage: pure ancestor-walk guards
  (chain order, missing entry, pid 0, self-parent, cycle, depth bound),
  env kill-switch semantics, installer disable/arm behavior (named daemon
  thread), and Windows-only real-handle assertions (parent chain
  discovery, explicit-pid dedupe and skip, creation-time monotonicity)
  against genuine kernel32 calls with no mocks.
- Add a `grace_seconds` parameter to `install_stdio_lifetime_watchdog` so
  tests control the arming window without patching module constants.

## Outcome

22 tests pass; ruff, basedpyright, ty green.

## Notes

An initial dead-PID assertion used PID 4 (openable here) and then a
zombie child (openable while the Popen handle lives); the stable choice
is PID 3, which can never name a Windows process.
