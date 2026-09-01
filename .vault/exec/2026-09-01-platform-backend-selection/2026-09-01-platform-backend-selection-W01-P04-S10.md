---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:87ad8a99d1c0cd28d67df727f5c6ff7de4b359e0c585bb7ec89db29a44f2542a'
step_id: 'S10'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---
# Place the lazy local reranker and retry path through the accelerator context

## Scope

- `src/vaultspec_rag/search/_searcher.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
