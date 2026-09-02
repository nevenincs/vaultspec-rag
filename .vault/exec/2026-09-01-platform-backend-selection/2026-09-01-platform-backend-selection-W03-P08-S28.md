---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:f96e23db0a556ad73031fddd88a574973a40ec498318e972f5ed876c27b970ed'
step_id: 'S28'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Describe accelerator selection and unified-memory behavior

## Scope

- `docs/architecture.md`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
