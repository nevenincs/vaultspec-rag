---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S10'
related:
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
---

# Carry initiator identity (pid, argv command line, cwd) on the cli_terminate audit event and in the stop and stop-port envelope data

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Added `_initiator_fields()` returning the terminating process' own pid,
  bounded argv command line (truncated at 300 chars), and cwd as string kv
  fields.
- Rewrote `_terminate_and_confirm` to emit the `cli_terminate` shutdown audit
  line on every platform (previously win32-only), reporting the real platform
  and carrying the initiator fields; the win32 rationale comment is preserved.
- Threaded `_initiator_fields()` into the `_stop_success` envelope data for the
  three paths that actually terminate or reclaim a process: `stopped` (default),
  `stopped` (`--port`), and `reclaimed`. The idempotent `already_stopped` and
  stale-state `cleaned` envelopes are left unchanged, since nothing was
  terminated.

## Outcome

A single shutdown log line and the terminating stop `--json` envelopes now
answer "who stopped the machine service" with the initiator pid, command line,
and cwd. Ruff, ruff format, and basedpyright all pass on the touched file.

## Notes

The audit line platform field now reflects `sys.platform` rather than a
hardcoded `win32`, keeping the mirror line honest on POSIX where it is
additive to the daemon's own clean-shutdown record. No skipped work.
