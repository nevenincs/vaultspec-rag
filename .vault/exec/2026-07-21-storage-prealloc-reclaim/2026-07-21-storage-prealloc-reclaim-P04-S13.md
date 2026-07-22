---
tags:
  - '#exec'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S13'
related:
  - "[[2026-07-21-storage-prealloc-reclaim-plan]]"
---

# Integration-test the convergence contract: a reconcile observed mid-flight is never reported as reclaimed, and the converged figure is the one recorded

## Scope

- `src/vaultspec_rag/tests/integration/test_storage_ops_integration.py`

## Description

- Add `test_unwaited_reconcile_never_reports_a_reclaim_figure` to `src/vaultspec_rag/tests/integration/test_storage_ops_integration.py`.
- Assert an unwaited reconcile reports `converging` with a null `bytes_after` and zero reclaimed bytes, that the setting still persists so the collection converges on its own, and that a later pass finds no drift left.

## Outcome

The convergence contract is proven end to end: a measurement is only reported when it has been waited for, and skipping the wait costs the figure but not the convergence. All 6 reconcile integration tests pass against a real qdrant server in 49 seconds.

## Notes

No incidents.
