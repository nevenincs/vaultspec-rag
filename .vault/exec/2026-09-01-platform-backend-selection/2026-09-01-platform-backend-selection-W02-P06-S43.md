---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-02'
body_schema: 'body-v1'
body_hash: 'sha256:9daa5e35dc1e2ffcca2c731d31b333aa8cb29bb7c860d9c871ef13f80808a852'
step_id: 'S43'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Update service lifecycle preflight to call the canonical accelerator loader

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
