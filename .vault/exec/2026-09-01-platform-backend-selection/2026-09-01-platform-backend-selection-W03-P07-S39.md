---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:93998a11c6e2c858c6ef436e3f5b816e1dbd4d4f9c542d2c5f65ff911ea0fccb'
step_id: 'S39'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Declare MPS as a distinct hardware tier without CUDA lease assumptions

## Scope

- `src/vaultspec_rag/tests/_tier_gate.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
