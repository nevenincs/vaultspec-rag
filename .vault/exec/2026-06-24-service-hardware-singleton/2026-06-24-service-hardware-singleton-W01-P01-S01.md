---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S01'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---




# Capture the qdrant child stdout and stderr to the log reliably across platforms

## Scope

- `src/vaultspec_rag/qdrant_runtime/_supervise.py`

## Description

- Replaced the raw stdout-to-file redirect in `QdrantSupervisor.spawn` with a piped capture:
  the child runs with `stdout=PIPE`, `stderr=STDOUT`, text mode, drained by a daemon thread.
- Added `_start_output_drain` and `_drain_output`: the drain appends each line to the log
  (opened owner-only with `O_NOFOLLOW` preserved) and to a bounded recent-output ring
  (`deque(maxlen=50)`), so an abnormal exit's output is retained rather than lost.
- Joined the drain thread (bounded) in `stop()` so the log handle is flushed and closed.

## Outcome

The child's combined output is now captured reliably even on an abrupt exit (a Rust panic,
a bind failure, a lock error) - the exact case where the prior file-redirect lost the panic
and produced an opaque timeout. `ruff` and `ty` pass; verified by the S03 drain test (ring +
log both receive the output).

## Notes

Inlined the Popen kwargs per branch (not via a shared dict) so the `text=True` overload
resolves to `Popen[str]` for the type checker. No blockers.
