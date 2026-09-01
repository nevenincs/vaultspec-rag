---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:5c7c5203a4a0946d0a271c5ea7e73b4afe526c586cb022c80c4b3839e7f9f7e8'
step_id: 'S46'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---
# Adapt sparse conversion parity fixtures to the canonical accelerator context.

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
