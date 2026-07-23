---
tags:
  - '#exec'
  - '#index-job-backend-resilience'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S04'
related:
  - "[[2026-07-23-index-job-backend-resilience-plan]]"
---

# Run the point-delete operations under the bounded retry

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Added a `_delete_points` helper running point removal under `_retried`.
- Routed all five `delete` call sites (delete by id list and delete by payload filter) through it.

## Outcome

Stale-point removal, which the incremental index path performs while reconciling superseded chunks, now tolerates a transient refusal. Deletion by id list or by payload filter is idempotent - replaying an attempt that already landed removes nothing further - so it satisfies the replay-safety rule for wrapping.

Collection drops remain outside the retry, as recorded in the ensure step: they are lifecycle-destructive, not idempotent point operations.

## Notes

The store suites (store, store writes, codebase store, qdrant resilience, document search, preprocess store) pass at 86 tests after the ensure, read, and delete wrapping together, confirming no behavioural regression in the wrapped paths.
