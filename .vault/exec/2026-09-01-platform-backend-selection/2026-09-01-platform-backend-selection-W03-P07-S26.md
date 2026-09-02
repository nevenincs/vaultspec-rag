---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:2312ebd93c7024d6394577a8a24172a09157b7cc4b4cfefd91e5434a566c6680'
step_id: 'S26'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Run the MPS guard only on the self-hosted Apple silicon job

## Scope

- `.github/workflows/ci.yml`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
