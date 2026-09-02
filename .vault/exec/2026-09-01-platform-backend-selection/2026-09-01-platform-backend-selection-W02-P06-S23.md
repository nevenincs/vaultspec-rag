---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:82a7f43f83d0bdc03934acb30374c9fbfa7a837771af2d55525da80703950d01'
step_id: 'S23'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Exercise supported-accelerator subprocess preflight and remediation

## Scope

- `src/vaultspec_rag/tests/test_service_env_preflight.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
