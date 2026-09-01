---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:79a44c08a6502e239b8c37826c6f42cfa366edfc11ae45a8b7737470ce06830c'
step_id: 'S29'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---
# Make the tutorial prerequisites valid for CUDA and Apple silicon

## Scope

- `docs/getting-started.md`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
