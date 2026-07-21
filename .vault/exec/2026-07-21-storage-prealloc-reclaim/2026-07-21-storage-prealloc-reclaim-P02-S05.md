---
tags:
  - '#exec'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S05'
related:
  - "[[2026-07-21-storage-prealloc-reclaim-plan]]"
---

# Add the reconcile enable, per-cycle cap, and convergence budget config knobs following existing naming conventions

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Add `VAULTSPEC_RAG_STORAGE_RECONCILE` (default true), `VAULTSPEC_RAG_STORAGE_RECONCILE_MAX_PER_CYCLE` (default 4), and `VAULTSPEC_RAG_STORAGE_RECONCILE_BUDGET_SECONDS` (default 300.0) to `src/vaultspec_rag/config.py`.
- Register the env-var enum entries, the mapping entries, and the commented defaults following the existing autoprune naming conventions.

## Outcome

Operators can enable or disable in-daemon reconciliation and bound its per-cycle work and time budget through the same configuration idiom as the existing autoprune knobs.

## Notes

No incidents.
