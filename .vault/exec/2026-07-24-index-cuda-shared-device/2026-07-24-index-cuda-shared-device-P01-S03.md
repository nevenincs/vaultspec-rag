---
tags:
  - '#exec'
  - '#index-cuda-shared-device'
date: '2026-07-24'
modified: '2026-07-27'
step_id: 'S03'
related:
  - "[[2026-07-24-index-cuda-shared-device-plan]]"
---

# pass the resident baseline into the ceiling derivation and move it after the admission cache flush in the codebase indexer budget builder

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Reorder `_begin_memory_budget` in `src/vaultspec_rag/indexer/_codebase_indexer.py` (`src/vaultspec_rag/indexer/_codebase_indexer.py:456-475`): the ceiling derivation previously ran BEFORE `reset_cuda_peak_memory_stats()`; it now runs after, so this process's allocator retention no longer depresses the free reading.
- Compute `cuda_baseline_mb = resident_cuda_baseline_mb() if uses_cuda else None` once and pass it both into `resolve_index_cuda_ceiling_mb(baseline_mb=...)` and into `MemoryBudget(cuda_baseline_mb=...)`, so derivation and enforcement share the same baseline.

## Outcome

Code-path budget builder samples free post-flush and derives the absolute ceiling from the same resident baseline enforcement nets out.

## Notes
Template evidence: intro_commit=58d6eb6527001b03b92a32cbb22c8cb999d28007; template_commit=58d6eb6527001b03b92a32cbb22c8cb999d28007:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
