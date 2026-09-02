---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:d5ccab4329f21addf0c8a209441bcd7c72f4064831a1778d166cf0ce867f5911'
step_id: 'S04'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Prove accelerator resolution order, CPU refusal, fallback refusal, and centralized torch loading

## Scope

- `src/vaultspec_rag/tests/test_torch_load_centralized.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
