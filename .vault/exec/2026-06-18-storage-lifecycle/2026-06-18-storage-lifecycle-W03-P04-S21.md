---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
body_hash: 'sha256:b81ddddbd030720508cb7021880bf193f42761d4f5892af66e6b6a5582af4b64'
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
