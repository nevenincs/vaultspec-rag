---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-24'
body_hash: 'sha256:900893b23cf614e6a73f14a53499336e254a4bf8490073563b5517cd3d23751c'
step_id: 'S14'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# update the budget class contract prose to state that allocated alone gates and reserved is reported

## Scope

- `src/vaultspec_rag/memory_probe.py`

## Description

- Rewrite the `MemoryBudget` class contract prose: the CUDA ceiling enforces the allocated high-water (demand); reserved is sampled and reported as a fragmentation diagnostic and never decides outcome.
- Update the `cuda_ceiling_mb` property docstring accordingly.

## Outcome

The contract prose states the enforcement split directly.

## Notes

Landed in commit `29168706` (same authorization as the enforcement removal).
