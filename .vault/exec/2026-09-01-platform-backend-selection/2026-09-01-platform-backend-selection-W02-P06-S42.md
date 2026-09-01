---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:8d08b4b64901abe145ce7c1a6f04fb9bc6fcb49db3faa49e17f859f4003186ef'
step_id: 'S42'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---
# Update installer accelerator diagnostics to use the canonical backend-neutral warning helper.

## Scope

- `src/vaultspec_rag/cli/_install.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
