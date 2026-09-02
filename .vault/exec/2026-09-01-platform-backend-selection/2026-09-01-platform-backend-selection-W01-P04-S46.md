---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-02'
body_schema: 'body-v1'
body_hash: 'sha256:34cce93fac01434d2d16038e976401dffdc324f62b86492fdf1ef7e66364c6f4'
step_id: 'S46'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Adapt sparse conversion parity fixtures to the canonical accelerator context

## Scope

- `src/vaultspec_rag/tests/test_encode_hygiene_unit.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
