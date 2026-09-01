---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:0c94d8cd4504e97bd5f16ba8dc9ef6f60224fcbc79487de62f593711913d7a0b'
step_id: 'S30'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---
# Document macOS installation, MPS fallback refusal, and platform-specific provisioning

## Scope

- `docs/installation.md`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
