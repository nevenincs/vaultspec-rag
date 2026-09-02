---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:cf59d4bf7ccf496ea9388be5ab8931ca756c6ea5e85f23cfd474b1229235bf3c'
step_id: 'S34'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Define accelerator, CUDA, MPS, and unified-memory terms

## Scope

- `docs/glossary.md`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
