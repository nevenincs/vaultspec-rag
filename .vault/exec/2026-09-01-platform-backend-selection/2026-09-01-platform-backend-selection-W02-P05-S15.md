---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:b8fa47292defdf5e84c5d8bc826aaaa05fdc83909ecbccf071c60f781abc6517'
step_id: 'S15'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---
# Diagnose torch and accelerator readiness for CUDA, MPS, and unavailable hosts

## Scope

- `src/vaultspec_rag/_readiness.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
