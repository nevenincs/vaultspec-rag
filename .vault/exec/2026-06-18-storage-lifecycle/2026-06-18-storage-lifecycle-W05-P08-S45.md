---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
body_hash: 'sha256:e6da1fee625d81d2b73eaf407cc8030572e626613ee4ad657c28229ae7ac0407'
step_id: 'S45'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Add a real-backend migrate round-trip test between local and server with an integrity check

## Scope

- `src/vaultspec_rag/tests/integration/test_storage_migrate.py`

## Description

- Add a real-backend migrate integration test (remap-copy, target-exists skip, missing-source skip).

## Outcome

Green against the temp server. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.
