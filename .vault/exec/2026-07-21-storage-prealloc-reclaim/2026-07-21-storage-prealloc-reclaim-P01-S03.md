---
tags:
  - '#exec'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:c47205cf4747a61489af7429501cf84ce69b606d3d7721b53a8cc0cf9360a690'
step_id: 'S03'
related:
  - "[[2026-07-21-storage-prealloc-reclaim-plan]]"
---

# Implement the capped batch reconcile over drifted collections with dry-run preview and deterministic ordering

## Scope

- `src/vaultspec_rag/storage_ops.py`

## Description

- Add the `ReconcileBatch` dataclass, the pure `plan_reconcile()` selection function, and `reconcile_collections()` to `src/vaultspec_rag/storage_ops.py`.
- Define drift as `segment_target != target` - the configured setting, not the observed segment count.
- Order selection largest-footprint-first, with unmeasured footprints sorting last.
- Return `would_reconcile` entries and mutate nothing under dry-run; update `__all__`.

## Outcome

Batch reconciliation selects and converges drifted collections under a cap, and a capped pass reclaims the most bytes it can. Keying drift off the setting rather than the actual segment count avoids flagging collections whose optimizer has legitimately grown segments to hold real data. Dry-run is a pure preview.

## Notes

No incidents.
