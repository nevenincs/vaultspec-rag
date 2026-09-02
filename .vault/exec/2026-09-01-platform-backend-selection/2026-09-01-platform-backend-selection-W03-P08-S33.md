---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:c40dfd2ac23b13c53999aace5f11b71c709f7ecd35379900369a3e7fb41f6afb'
step_id: 'S33'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Update readiness and model-download command contracts for supported accelerators

## Scope

- `docs/cli.md`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
