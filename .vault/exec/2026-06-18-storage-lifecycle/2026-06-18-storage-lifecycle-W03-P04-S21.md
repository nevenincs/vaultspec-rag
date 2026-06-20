---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
step_id: 'S21'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Drop the root namespaced collections in server mode and remove the local store tree only when the store is confirmed closed

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Drop the prefix's collections via the Qdrant client delete_collection (server-mode authority).

## Outcome

Collections removed; verified by collection_exists assertions in integration. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.
