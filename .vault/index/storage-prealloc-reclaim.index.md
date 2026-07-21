---
generated: true
tags:
  - '#index'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - '[[2026-07-21-storage-prealloc-reclaim-P01-S01]]'
  - '[[2026-07-21-storage-prealloc-reclaim-P01-S02]]'
  - '[[2026-07-21-storage-prealloc-reclaim-P01-S03]]'
  - '[[2026-07-21-storage-prealloc-reclaim-P01-S04]]'
  - '[[2026-07-21-storage-prealloc-reclaim-P02-S05]]'
  - '[[2026-07-21-storage-prealloc-reclaim-P02-S06]]'
  - '[[2026-07-21-storage-prealloc-reclaim-P02-S07]]'
  - '[[2026-07-21-storage-prealloc-reclaim-P02-S08]]'
  - '[[2026-07-21-storage-prealloc-reclaim-P03-S09]]'
  - '[[2026-07-21-storage-prealloc-reclaim-P03-S10]]'
  - '[[2026-07-21-storage-prealloc-reclaim-P03-S11]]'
  - '[[2026-07-21-storage-prealloc-reclaim-P04-S12]]'
  - '[[2026-07-21-storage-prealloc-reclaim-P04-S13]]'
  - '[[2026-07-21-storage-prealloc-reclaim-P05-S14]]'
  - '[[2026-07-21-storage-prealloc-reclaim-P05-S15]]'
  - '[[2026-07-21-storage-prealloc-reclaim-adr]]'
  - '[[2026-07-21-storage-prealloc-reclaim-plan]]'
  - '[[2026-07-21-storage-prealloc-reclaim-research]]'
---

# `storage-prealloc-reclaim` feature index

Auto-generated index of all documents tagged with `#storage-prealloc-reclaim`.

## Documents

### adr

- `2026-07-21-storage-prealloc-reclaim-adr` - `storage-prealloc-reclaim` adr: `in-place collection geometry reconcile` | (**status:** `accepted`)

### exec

- `2026-07-21-storage-prealloc-reclaim-P01-S01` - Declare the bounded-geometry target as shared constants and add a drift predicate that compares a live collection's optimizer segment target against it
- `2026-07-21-storage-prealloc-reclaim-P01-S02` - Implement single-collection reconcile: issue the optimizer config update, then wait for segment-count and directory-size stability under a bounded budget, returning reconciled / converging / failed outcomes
- `2026-07-21-storage-prealloc-reclaim-P01-S03` - Implement the capped batch reconcile over drifted collections with dry-run preview and deterministic ordering
- `2026-07-21-storage-prealloc-reclaim-P01-S04` - Unit-test drift detection, idempotent skip of converged collections, cap and dry-run behaviour, and that a budget expiry reports converging with no reclaim figure
- `2026-07-21-storage-prealloc-reclaim-P02-S05` - Add the reconcile enable, per-cycle cap, and convergence budget config knobs following existing naming conventions
- `2026-07-21-storage-prealloc-reclaim-P02-S06` - Run the reconcile stage from the maintenance cycle ahead of reclamation evaluation and carry its counts and reclaimed bytes on the maintenance result
- `2026-07-21-storage-prealloc-reclaim-P02-S07` - Emit reconcile counters, the drifted-collection gauge, and completion-only log lines from the maintenance tick
- `2026-07-21-storage-prealloc-reclaim-P02-S08` - Extend the lifecycle-inertness regression guard to cover the reconcile surface
- `2026-07-21-storage-prealloc-reclaim-P03-S09` - Surface geometry drift and its pending reclamation in the survey and its rollup
- `2026-07-21-storage-prealloc-reclaim-P03-S10` - Add the storage reconcile verb with preview, collection bound, and no-wait mode, emitting exactly one structured envelope per exit path
- `2026-07-21-storage-prealloc-reclaim-P03-S11` - Test the verb's structured outcomes including the no-drift success and the dry-run no-mutation guarantee
- `2026-07-21-storage-prealloc-reclaim-P04-S12` - Integration-test that reconcile against a real server reclaims measured bytes, preserves exact point counts, and leaves dense search results identical
- `2026-07-21-storage-prealloc-reclaim-P04-S13` - Integration-test the convergence contract: a reconcile observed mid-flight is never reported as reclaimed, and the converged figure is the one recorded
- `2026-07-21-storage-prealloc-reclaim-P05-S14` - Document the reconcile contract, the automatic convergence behaviour, and the accepted write-ahead log residue
- `2026-07-21-storage-prealloc-reclaim-P05-S15` - Bring lint, type, and unit gates green across the changed surface

### plan

- `2026-07-21-storage-prealloc-reclaim-plan` - `storage-prealloc-reclaim` plan

### research

- `2026-07-21-storage-prealloc-reclaim-research` - `storage-prealloc-reclaim` research: `reclaiming per-collection preallocation from existing collections`
