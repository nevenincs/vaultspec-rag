---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:52b99b75f48e0689d9bad062d2d3ac55df4aa2429cd8be9b48acba94132a65cb'
step_id: 'S32'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Document service startup and preflight for CUDA and MPS

## Scope

- `docs/service-mode.md`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
