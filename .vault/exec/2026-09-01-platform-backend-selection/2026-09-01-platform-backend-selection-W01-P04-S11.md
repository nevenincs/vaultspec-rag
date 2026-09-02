---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:55dd0216c82e9973fa799eeef689062e8546cf246f39e2e7479f21fc54b266d1'
step_id: 'S11'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Release accelerator caches through the canonical backend operation

## Scope

- `src/vaultspec_rag/indexer/_streaming.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
