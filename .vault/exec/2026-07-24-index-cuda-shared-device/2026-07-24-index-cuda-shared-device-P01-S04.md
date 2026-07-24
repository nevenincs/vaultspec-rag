---
tags:
  - '#exec'
  - '#index-cuda-shared-device'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S04'
related:
  - "[[2026-07-24-index-cuda-shared-device-plan]]"
---

# pass the resident baseline into the ceiling derivation and keep it after the admission cache flush in the document indexer budget builder

## Scope

- `src/vaultspec_rag/indexer/_document_indexer.py`

## Description

- Keep `_begin_resource_budget` in `src/vaultspec_rag/indexer/_document_indexer.py` deriving AFTER `reset_cuda_peak_memory_stats()` (it already did).
- Compute `cuda_baseline_mb = resident_cuda_baseline_mb() if uses_cuda else None` once, pass `baseline_mb=cuda_baseline_mb or 0.0` into `resolve_index_cuda_ceiling_mb` and the same value into `_DocumentResourceBudget(cuda_baseline_mb=...)`.

## Outcome

Document-path budget builder now feeds the resident baseline into the absolute derivation while retaining its post-flush sampling order; both indexers sample free after the admission cache flush.

## Notes
