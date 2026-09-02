---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:5804f7c88adf7ecca9422bff55cca57096ea645010964e946265627bec1f3168'
step_id: 'S19'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Classify missing, CUDA, MPS, and CPU-only torch environments

## Scope

- `src/vaultspec_rag/cli/_gpu_errors.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
