---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:0fe12095982e0ae0069819a3d297f664c6ca4d3d1fdfbcb745792f79fd2bcde5'
step_id: 'S41'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Prove MPS marker selection and exclusion discipline can fail on drift

## Scope

- `src/vaultspec_rag/tests/test_marker_discipline.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
