---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:5c8d975ead5fd312d2db52d497b728c5f66427c11b42aa8047ca8033c329ade0'
step_id: 'S31'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Describe dense, sparse, and reranker execution on the selected accelerator

## Scope

- `docs/indexing.md`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
