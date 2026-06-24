---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S03'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---




# Test that a non-ready child surfaces its cause instead of an opaque timeout

## Scope

- `src/vaultspec_rag/tests/test_qdrant_supervise_diagnostics.py`

## Description

- Authored `test_qdrant_supervise_diagnostics.py` (no mocks, no GPU): drives `_drain_output`
  with a real in-memory stream and asserts the panic line reaches both the recent-output ring
  and the log file; asserts the ring is bounded (oldest dropped); and points the supervisor at
  the real interpreter (a benign never-serving child) to assert `start()` raises a bounded,
  cause-naming error rather than hanging to the 300s default.

## Outcome

3 tests pass in ~4.5s with no GPU. The legibility guarantees (capture + bounded, named
failure) are verified. `ruff` and `ty` pass.

## Notes

Used a free, non-default port (599xx) so the test can never touch a running Qdrant on 8765.
The fast-fail timing assertion was relaxed to a bounded-not-300s check, since how quickly the
benign interpreter child exits is environment-dependent; the load-bearing assertions are the
captured cause and the bounded wait. No blockers.
