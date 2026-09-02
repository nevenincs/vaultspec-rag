---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:bdbde4076a66f009be68173308aaad76e0cc23d4e33f468b864d86e6dfab2183'
step_id: 'S21'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Render accelerator backend and memory semantics in human status output

## Scope

- `src/vaultspec_rag/cli/_status.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
