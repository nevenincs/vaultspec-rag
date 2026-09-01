---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:91cdbdc6d90469390ef5a39f790576f168ecde8158b97052fe253a598acf6926'
step_id: 'S40'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---
# Guard explicitly selected MPS tests on Apple silicon without CUDA coordination

## Scope

- `src/vaultspec_rag/tests/conftest.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
