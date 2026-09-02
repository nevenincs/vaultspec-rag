---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:86ad422e4176fcec0b18e60f1e4ec7066b55d74cc8c74c77af7c16630df9034a'
step_id: 'S37'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Exercise CUDA, MPS, and unavailable torch configuration diagnosis

## Scope

- `src/vaultspec_rag/tests/test_torch_config.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
