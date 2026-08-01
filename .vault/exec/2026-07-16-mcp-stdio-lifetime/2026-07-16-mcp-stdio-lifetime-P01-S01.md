---
tags:
  - '#exec'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-17'
body_hash: 'sha256:d1b3893350d238d9df95e65848153d8b4abed5a72fddff7dbbde98b01037ec31'
step_id: 'S01'
related:
  - "[[2026-07-16-mcp-stdio-lifetime-plan]]"
---

# Create the watchdog module with ctypes kernel32 bindings (full argtypes and restype), Toolhelp32 ancestor-chain discovery bounded and cycle-safe, creation-time monotonicity PID-reuse guard, and immediate SYNCHRONIZE handle acquisition

## Scope

- `src/vaultspec_rag/server/_stdio_lifetime.py`

## Description

- Create `src/vaultspec_rag/server/_stdio_lifetime.py` with the module
  docstring stating the lifetime contract and thin-client constraints.
- Bind kernel32 (`CreateToolhelp32Snapshot`, `Process32First/Next`,
  `OpenProcess`, `CloseHandle`, `GetProcessTimes`, `WaitForSingleObject`,
  `WaitForMultipleObjects`) with full argtypes/restype under a
  `sys.platform == "win32"` guard.
- Implement `_walk_ancestor_pids` as a pure, cross-platform, bounded and
  cycle-safe parent-map walk (unit-testable without Windows APIs).
- Implement `_snapshot_processes`, `_creation_time`, `_open_process`, and
  `open_ancestor_handles` with immediate SYNCHRONIZE handle acquisition,
  creation-time monotonicity as the PID-reuse guard, and explicit
  `--parent-pid` extras watched ahead of discovery.
- Add the `watchdog_disabled` env-knob probe (`VAULTSPEC_RAG_STDIO_WATCHDOG`).

## Outcome

Module compiles clean: ruff check/format, basedpyright, and ty all pass.
Arming/trigger logic lands in the next Step.

## Notes

The explicit-signature mandate exists because the research prototype's
undeclared ctypes bindings failed silently (research finding W2).
