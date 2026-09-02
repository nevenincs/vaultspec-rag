---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:bb38faed83961e986d9d6b8594ac679decbc7a5b80f3e22f00bb062896f3f892'
step_id: 'S08'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Place dense and sparse models through the accelerator context and use backend-neutral recovery

## Scope

- `src/vaultspec_rag/embeddings.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
