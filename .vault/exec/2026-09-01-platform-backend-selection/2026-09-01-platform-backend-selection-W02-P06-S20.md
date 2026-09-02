---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:d15ff6acf6a2e08109d70e4ce50a5f56f877be054021ef51cb3cb0139f060a0a'
step_id: 'S20'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Probe the service interpreter for any supported accelerator without importing torch into the caller

## Scope

- `src/vaultspec_rag/cli/_process.py`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
