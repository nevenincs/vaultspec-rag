---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S02'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---




# Report a non-ready child exit with the captured log tail and a named cause

## Scope

- `src/vaultspec_rag/qdrant_runtime/_supervise.py`

## Description

- Added `recent_output_tail(max_lines)` returning the joined most-recent captured lines.
- Changed `start()` so a non-ready exit raises with the captured cause: the error names the
  port and timeout and appends either the last child output or an explicit "produced no
  output before exiting" note - never a silent/opaque failure.

## Outcome

A failed Qdrant startup now reports its cause (a panic backtrace, a bind/lock error) instead
of only "failed to become ready within Ns". `ruff` and `ty` pass; verified by the S03 test
asserting the raised message contains the cause and the wait is bounded by the timeout, not
the 300s default.

## Notes

Same-file continuation of S01 (the capture mechanism it reports from). No blockers.
