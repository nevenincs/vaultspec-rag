---
tags:
  - '#exec'
  - '#index-job-backend-resilience'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S02'
related:
  - "[[2026-07-23-index-job-backend-resilience-plan]]"
---

# Run the collection-ensure paths (existence check and payload-index creation) under the bounded retry

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Added a private `_retried` helper on the store that routes one replay-safe operation through the bounded retry, and is deliberately server-mode only.
- Added `_collection_exists` and `_create_payload_index` helpers that run those operations under `_retried`.
- Routed all seven `collection_exists` call sites and all six `create_payload_index` call sites through the new helpers.

## Outcome

The collection-ensure path - the first backend contact an index job makes, and therefore the operation a refused connection kills first - now rides out a transient refusal. In the steady state of an index update the collection already exists, so the ensure path is exactly the existence check plus the idempotent index creation, and both are now covered.

Deliberately excluded: `create_collection` and `delete_collection` are not routed through the retry. Neither is replay-safe - a lost response on a create would make the retry fail with an already-exists error, and dropping a collection is lifecycle-destructive rather than idempotent. The ADR's rule is that only replay-safe operations are wrapped, and these are not.

Local mode is excluded by design: the embedded engine has no socket to refuse, so `_retried` runs the operation exactly once there and a genuine local fault surfaces immediately instead of being retried five times.

## Notes

The first mechanical rewrite of the `collection_exists` call sites also rewrote the body of `_collection_exists` itself, creating unbounded recursion; caught immediately and corrected so the helper calls the client directly.

Code review raised two follow-ups here, both applied. The process-global warning suppression around payload-index creation was wrapping the whole retry, so it spanned backoff sleeps; since it mutates global filter state and is not thread-safe, it was moved inside a single attempt. And review confirmed the lock analysis: the retry acquires nothing and calls back into nothing, so there is no deadlock or lock-ordering violation, and because point locks are a null context in server mode every wrapped read and delete retries with no collection lock held. The lifecycle lock is the one genuine exposure, which the new per-operation wall-clock ceiling bounds.
