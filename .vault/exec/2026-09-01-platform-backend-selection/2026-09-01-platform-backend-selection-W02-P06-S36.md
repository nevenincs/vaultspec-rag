---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:d76d1244091206420173ed5cd666b9acba5ff19d35d71a1345097420422bac5b'
step_id: 'S36'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---
# Invoke the canonical supported-accelerator subprocess probe during service startup

## Scope

- `src/vaultspec_rag/cli/_service_start.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
