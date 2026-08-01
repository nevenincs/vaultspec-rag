---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
body_hash: 'sha256:d81c4c80f98feac343bc19162087aec59674e11499eed91130b6148992b509e4'
step_id: 'S26'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Add real-backend delete tests for server and local including the busy-root path

## Scope

- `src/vaultspec_rag/tests/integration/test_storage_delete.py`

## Description

- Add real-backend delete tests (unknown-refusal path).

## Outcome

Green against the temp server. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.
