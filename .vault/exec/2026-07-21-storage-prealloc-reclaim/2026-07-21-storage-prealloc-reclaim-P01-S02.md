---
tags:
  - '#exec'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S02'
related:
  - "[[2026-07-21-storage-prealloc-reclaim-plan]]"
---

# Implement single-collection reconcile: issue the optimizer config update, then wait for segment-count and directory-size stability under a bounded budget, returning reconciled / converging / failed outcomes

## Scope

- `src/vaultspec_rag/storage_ops.py`

## Description

- Add the `ReconcileResult` dataclass, `reconcile_collection()`, and `_await_convergence()` to `src/vaultspec_rag/storage_ops.py`.
- Issue `update_collection` with an optimizer config carrying the bounded segment target, then wait for the collection to settle.
- Define convergence as stability: four consecutive samples at a 1s poll must agree on segment count and directory size within a 1 MiB tolerance while the collection reports a settled optimizer status.
- Report `reclaimed_bytes` as a property that returns 0 unless both before and after measurements exist, clamped at 0.

## Outcome

A single collection can now be converged in place to the bounded geometry and reports one of `reconciled`, `converging`, or `failed`. Only an error from the update call is a failure; budget expiry reports `converging` and deliberately carries no reclaim figure, since a mid-merge measurement would be misleading. An apparent growth can never surface as a negative reclamation.

## Notes

No incidents.
