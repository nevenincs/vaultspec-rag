---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:5d42f027d16aa96fa2084472e9bfbcd2715105b41ef404a3518a4e678adfb728'
step_id: 'S44'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---
# Update resilience benchmarks to consume the canonical accelerator context.

## Scope

- `src/vaultspec_rag/tests/benchmarks/bench_large_index_resilience.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
