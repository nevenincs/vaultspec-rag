---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:93ea4ef64f4605556dbcbdfda3fbbfe001fc12d271ef1558b8d8456683bf5410'
step_id: 'S02'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---
# Generalize load admission for CUDA memory policy and MPS capability policy under one load window

## Scope

- `src/vaultspec_rag/_gpu_admission.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
