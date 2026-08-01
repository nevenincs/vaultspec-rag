---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:4ae93d816e8b649fa5d1e73b0d790ee364f84f093844632e74cc7eab859252c1'
step_id: 'S15'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# make the ceiling comparison baseline-consistent by subtracting the baseline from the captured peak and from the derived ceiling on the same side

## Scope

- `src/vaultspec_rag/memory_probe.py`

## Description

- Make the ceiling comparison baseline-consistent in `MemoryBudget._classify_failure`: the resident baseline is subtracted from the captured peak AND from the ceiling on the same side, with both terms clamped at zero.
- Thread `cuda_baseline_mb` through budget construction at both enforcing sites (`_begin_memory_budget` in the codebase indexer, `_DocumentResourceBudget`/`_begin_resource_budget` in the document indexer) from `resident_cuda_baseline_mb`.
- Name the baseline-relative measure in the failure detail so the operator reads indexing demand against indexing headroom.

## Outcome

A captured peak is absolute (a post-rebase counter starts at the resident models); subtracting the baseline from only one side would double-count the models and covertly tighten the ceiling into a regression. The symmetric subtraction is mathematically equivalent to the absolute comparison in the normal regime, and the reported values describe indexing headroom.

## Notes

None.
