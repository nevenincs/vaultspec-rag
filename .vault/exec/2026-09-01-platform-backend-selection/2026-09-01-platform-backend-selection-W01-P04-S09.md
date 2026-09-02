---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:94b19a0379b9ca0b26b19a6b3b36f9f5df23a12214827f9fd2af0d5c0bff6bb6'
step_id: 'S09'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Place the shared resident reranker through the accelerator context

## Scope

- `src/vaultspec_rag/service.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
