---
tags:
  - '#exec'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S06'
related:
  - "[[2026-07-21-storage-prealloc-reclaim-plan]]"
---

# Run the reconcile stage from the maintenance cycle ahead of reclamation evaluation and carry its counts and reclaimed bytes on the maintenance result

## Scope

- `src/vaultspec_rag/storage_ops.py`

## Description

- Extend `ReclaimPolicy` in `src/vaultspec_rag/storage_ops.py` with `reconcile`, `reconcile_max_per_cycle`, and `reconcile_budget_seconds`.
- Add a `reconcile` field to `MaintenanceResult`, tracked separately from `reclaimed_bytes`.
- Run the reconcile stage from `run_maintenance_cycle`, after reclamation evaluation.

## Outcome

The maintenance cycle now converges drifted collections under the configured cap and budget, and reports reconcile results distinctly from reclamation. The two figures stay separate because reconcile releases preallocation from collections that are kept, while reclamation releases the footprint of namespaces that are destroyed.

## Notes

Deliberate deviation from the ADR: the reconcile stage was specified to run before reclamation evaluation. It was moved to run after reclamation so a convergence budget is never spent converging a namespace the same cycle is about to destroy. The ADR text was amended to match the shipped ordering.
