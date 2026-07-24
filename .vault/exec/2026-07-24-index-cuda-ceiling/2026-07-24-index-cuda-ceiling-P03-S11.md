---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S11'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# sample the resident-model baseline after every model including the lazily-loaded reranker is resident

## Scope

- `src/vaultspec_rag/service.py`

## Description

- Call `sample_resident_cuda_baseline` in `src/vaultspec_rag/service.py` after the eager `EmbeddingModel` load and again after the lazy `CrossEncoder` load in `get_reranker`.
- Implement the baseline store in `src/vaultspec_rag/memory_probe.py` as a lock-guarded monotonic maximum of the live allocated reading, so a late lazy load raises the figure and a transient dip never shrinks what an in-flight budget was constructed against.

## Outcome

The resident-model baseline is recorded after every model, including the reranker that loads outside the GPU lock; indexing budgets read it via `resident_cuda_baseline_mb`.

## Notes

None.
