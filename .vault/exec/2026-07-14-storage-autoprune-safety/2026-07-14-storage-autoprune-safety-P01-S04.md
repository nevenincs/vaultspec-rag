---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
body_hash: 'sha256:d2cedb176c920860df9a56214f683a859f7e4fdd2a381ab52e7cf771ec2a8461'
step_id: 'S04'
related:
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
---

# Cover the grace bookkeeping and eligibility gates with unit tests: stamping, restart persistence, reappearance reset, empty-vs-data tiering, cap enforcement, and archive retention

## Scope

- `src/vaultspec_rag/tests/test_storage_ops.py`

## Description

- Add `test_storage_ops.py` (15 tests) covering the grace clock through the
  real manifest under an isolated status dir: stamping, restart
  persistence, live/unverifiable reset, unknown-prefix no-op.
- Cover `evaluate_reclaim`: unstamped and young orphans pend, aged empty
  orphans become eligible, the data tier needs its longer window,
  non-orphaned statuses never appear, the cycle cap defers with the
  riskless empty tier filling first, and a garbage stamp restarts the
  window rather than qualifying.
- Cover `sweep_archive` on real temp files: missing-dir no-op, age-based
  retention, oldest-first byte-cap eviction.

## Outcome

15/15 passing; ruff and basedpyright clean. The client-coupled paths
(`archive_prefix`, `run_maintenance_cycle`) are deferred to the live
integration tier per the plan.

## Notes

None.
