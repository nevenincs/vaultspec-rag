---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S31'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Add a real-backend prune test that creates an orphaned namespace and asserts it is reclaimed while unknown namespaces are untouched

## Scope

- `src/vaultspec_rag/tests/integration/test_storage_prune.py`

## Description

- Add a real-backend prune integration test (orphaned reclaimed, unknown untouched).

## Outcome

Green against the temp server. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.
