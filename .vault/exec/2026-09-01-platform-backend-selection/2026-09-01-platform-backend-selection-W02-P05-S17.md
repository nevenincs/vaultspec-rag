---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:6bee851e4b14c1f349dd1e718a8ad5cc1439dd9fc9c51927a808ac712e05396e'
step_id: 'S17'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Exercise backend-neutral readiness payloads and torch-free probing

## Scope

- `src/vaultspec_rag/tests/test_readiness.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
