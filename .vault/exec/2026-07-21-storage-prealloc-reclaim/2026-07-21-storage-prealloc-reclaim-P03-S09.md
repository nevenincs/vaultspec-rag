---
tags:
  - '#exec'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-22'
step_id: 'S09'
related:
  - "[[2026-07-21-storage-prealloc-reclaim-plan]]"
---

# Surface geometry drift and its pending reclamation in the survey and its rollup

## Scope

- `src/vaultspec_rag/storage_ops.py`
- `src/vaultspec_rag/storage_survey.py`

## Description

- Surface geometry drift through `read_geometry()` and the `drifted_remaining` count on `ReconcileBatch` in `src/vaultspec_rag/storage_ops.py`.
- Consume both from the maintenance rollup and the CLI, and export the count as the `store_drifted_namespaces` gauge.

## Outcome

Drift is visible to an operator before any reconcile is authorised: the per-collection segment target and footprint come from `read_geometry()`, and the outstanding count is carried on every batch result and exported as a gauge.

## Notes

No incidents.
