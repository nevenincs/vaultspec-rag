---
tags:
  - '#exec'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S04'
related:
  - "[[2026-07-21-storage-prealloc-reclaim-plan]]"
---

# Unit-test drift detection, idempotent skip of converged collections, cap and dry-run behaviour, and that a budget expiry reports converging with no reclaim figure

## Scope

- `src/vaultspec_rag/tests/test_storage_ops.py`

## Description

- Add `TestPlanReconcile` (7 tests) and `TestReconcileResultReclaim` (3 tests) to `src/vaultspec_rag/tests/test_storage_ops.py`.
- Cover selection: already-at-target is not drifted; a high actual segment count does not imply drift; the server default `0` is drifted; the cap defers the remainder; largest-footprint-first ordering holds; an unmeasured footprint sorts last without being dropped; a zero cap selects nothing.
- Cover the reclaim-figure rules on `ReconcileResult`.

## Outcome

The selection predicate and the reclaim-figure contract are pinned by 10 passing unit tests. No test doubles were introduced: only the pure logic is unit-tested, and the client-coupled paths are covered at the integration tier against a real server.

## Notes

No incidents.
