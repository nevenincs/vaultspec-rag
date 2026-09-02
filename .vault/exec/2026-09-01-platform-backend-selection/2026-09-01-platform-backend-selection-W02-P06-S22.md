---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:df2da082df2c944ebb8645161acf9bfbbf2bdc73f1faf80d6e33b278416a5124'
step_id: 'S22'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Generalize torch configuration diagnosis beyond CUDA availability

## Scope

- `src/vaultspec_rag/torch_config/_diagnose.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
