---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-24'
step_id: 'S11'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# remove the reserved high-water comparison from ceiling enforcement leaving the allocated comparison as the sole gate

## Scope

- `src/vaultspec_rag/memory_probe.py`

## Description

- Remove the `peak_cuda_reserved_mb` comparison from `MemoryBudget._classify_failure` in `src/vaultspec_rag/memory_probe.py`, leaving the allocated high-water comparison as the sole CUDA gate.

## Outcome

A job fails on the demand it created, never on the caching allocator's retention history; failure attribution names work that genuinely demanded the memory.

## Notes

Landed earlier the same day in commit `29168706` under a direct user order to fix the regression immediately; this record documents it against the plan. That commit also switched the support-profile CUDA dimension projection in both indexers from reserved to allocated - the managed-service profile limit equals the ceiling, so projecting reserved would have resurrected the identical failure as a corpus-limit rejection.
