---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-02'
body_schema: 'body-v1'
body_hash: 'sha256:ed0d9b95f4e5df55ef7e8569f277b12ffef107404d4f965a99a7c782cadc754a'
step_id: 'S47'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Retarget bounded encode-recovery architecture guards to backend-neutral OOM classification

## Scope

- `src/vaultspec_rag/tests/test_adr_regression.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
