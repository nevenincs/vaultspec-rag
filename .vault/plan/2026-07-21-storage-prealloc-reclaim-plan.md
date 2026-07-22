---
tags:
  - '#plan'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-22'
tier: L2
related:
  - '[[2026-07-21-storage-prealloc-reclaim-adr]]'
  - '[[2026-07-21-storage-prealloc-reclaim-research]]'
---

# `storage-prealloc-reclaim` plan

### Phase `P01` - Drift detection and the reconcile primitive

Establish geometry drift as a readable property of a live collection and implement the single-collection reconcile with the bounded, stability-based convergence wait the ADR requires.

- [x] `P01.S01` - Declare the bounded-geometry target as shared constants and add a drift predicate that compares a live collection's optimizer segment target against it; `src/vaultspec_rag/storage_ops.py, src/vaultspec_rag/store.py`.
- [x] `P01.S02` - Implement single-collection reconcile: issue the optimizer config update, then wait for segment-count and directory-size stability under a bounded budget, returning reconciled / converging / failed outcomes; `src/vaultspec_rag/storage_ops.py`.
- [x] `P01.S03` - Implement the capped batch reconcile over drifted collections with dry-run preview and deterministic ordering; `src/vaultspec_rag/storage_ops.py`.
- [x] `P01.S04` - Unit-test drift detection, prefix scoping, idempotent skip of converged collections, cap and dry-run behaviour, and the convergence contract against a scripted optimizer timeline; `src/vaultspec_rag/tests/test_storage_ops.py`.

### Phase `P02` - Scheduled convergence

Wire the reconcile stage into the storage maintenance cycle behind config knobs, report it through the existing maintenance result, and extend the lifecycle-inertness guard.

- [x] `P02.S05` - Add the reconcile enable, per-cycle cap, and convergence budget config knobs following existing naming conventions; `src/vaultspec_rag/config.py`.
- [x] `P02.S06` - Run the reconcile stage from the maintenance cycle after reclamation, so no convergence budget is spent on a namespace the same cycle destroys, and carry its counts and reclaimed bytes on the maintenance result; `src/vaultspec_rag/storage_ops.py`.
- [x] `P02.S07` - Emit reconcile counters, the drifted-collection gauge, and completion-only log lines from the maintenance tick; `src/vaultspec_rag/server/_lifecycle.py`.
- [x] `P02.S08` - Extend the lifecycle-inertness regression guard to cover the reconcile surface; `src/vaultspec_rag/tests/test_adr_regression.py`.

### Phase `P03` - Operator surface

Expose drift in the survey and add the structured reconcile verb to the storage command group.

- [x] `P03.S09` - Expose geometry drift without authorising a change, through the non-mutating reconcile preview and the not-yet-converged gauge; `src/vaultspec_rag/storage_ops.py`.
- [x] `P03.S10` - Add the storage reconcile verb with preview, collection bound, and no-wait mode, emitting exactly one structured envelope per exit path; `src/vaultspec_rag/cli/_service_storage.py`.
- [x] `P03.S11` - Test the verb's structured outcomes including the no-drift success, the preview status, and the dry-run no-mutation guarantee; `src/vaultspec_rag/tests/test_storage_adversarial.py`.

### Phase `P04` - Real-qdrant validation

Prove reclamation, point preservation, search equivalence, and convergence stability against a real server with production collection geometry.

- [x] `P04.S12` - Integration-test that reconcile against a real server reclaims measured bytes, preserves exact point counts, and leaves dense search results identical; `src/vaultspec_rag/tests/integration/test_storage_ops_integration.py`.
- [x] `P04.S13` - Integration-test the convergence contract: a reconcile observed mid-flight is never reported as reclaimed, and the converged figure is the one recorded; `src/vaultspec_rag/tests/integration/test_storage_ops_integration.py`.

### Phase `P05` - Documentation and gates

Document the reconcile contract and accepted WAL residue, then bring lint, type, and test gates green.

- [x] `P05.S14` - Document the reconcile contract, the automatic convergence behaviour, and the accepted write-ahead log residue; `docs/storage.md`.
- [x] `P05.S15` - Bring lint, type, and unit gates green across the changed surface; `src/vaultspec_rag`.

## Description

## Steps

## Parallelization

## Verification
