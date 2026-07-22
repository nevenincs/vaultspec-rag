---
tags:
  - '#exec'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-22'
step_id: 'S08'
related:
  - "[[2026-07-21-storage-prealloc-reclaim-plan]]"
---

# Extend the lifecycle-inertness regression guard to cover the reconcile surface

## Scope

- `src/vaultspec_rag/tests/test_adr_regression.py`

## Description

- Confirm the existing lifecycle-inertness guard already covers `storage_ops`, so it extends to the reconcile surface unchanged.
- Add `TestGeometryReconcileIsNonDestructive` to `src/vaultspec_rag/tests/test_adr_regression.py` asserting reconcile function sources never name `delete_collection`, `delete_prefix`, `_delete_collection_hard`, `rmtree`, or `delete_points`.
- Assert the reconcile target matches the create-time geometry constant.

## Outcome

4 passing regression tests pin reconciliation as non-destructive and lifecycle-inert. The destructive-name guard blocks a future edit that reaches for a delete to reset a stubborn collection, and the target guard stops creation and reconciliation drifting apart in a way that would make every newly created collection read as drifted.

## Notes

No incidents.
