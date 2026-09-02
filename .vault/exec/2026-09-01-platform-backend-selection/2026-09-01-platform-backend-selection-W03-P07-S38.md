---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:c4673c905019257b480f718d8023175043fc6d3ace46a40c7ee7e81bf2732c8b'
step_id: 'S38'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Route the MPS hardware tier independently from ordinary and CUDA test recipes

## Scope

- `justfile`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
