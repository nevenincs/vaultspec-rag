---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
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
