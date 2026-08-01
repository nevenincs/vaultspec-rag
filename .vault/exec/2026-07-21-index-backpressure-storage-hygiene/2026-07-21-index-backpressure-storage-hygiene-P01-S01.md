---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:3b2dba2127e5e3e107ebb4d02cbfaf49291cdd0ce4c0faf477cdb95be4834397'
step_id: 'S01'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# add a configurable server-mode qdrant client timeout and a write-side classification wrapper around upsert_document_chunks and upsert_code_chunks (typed StorageWriteError with error_kind, bounded retry for transient kinds, disk_full non-retryable)

## Scope

- `src/vaultspec_rag/store.py`

## Description

Added `StorageWriteError` (carrying a stable `error_kind`), the
`_classify_write_error` mapper (`disk_full` via errno 28 and the qdrant
WAL/optimizer space messages, `timeout`, `unavailable`, `rejected`), and
the `_upsert_points` wrapper: bounded linear-backoff retry for transient
kinds only, immediate raise for `disk_full` and `rejected`. All three
upsert entry points (`upsert_documents`, `upsert_document_chunks`,
`upsert_code_chunks`) now route through it, and the server-mode client is
constructed with an explicit `qdrant_client_timeout_s` timeout so a
wedged server raises instead of hanging on transport defaults.

## Outcome

Committed as `feat(store): classified bounded-retry upserts and explicit client timeout (#242)`. Unit-verified by `test_store_write_unit.py`
(classification table, no-retry for disk_full/rejected, bounded budget,
cause chain).

## Notes

The point lock is a no-op in server mode, so the retry loop adds no lock
hold; local mode retries hold the collection RLock only per attempt. The
scope list above corrects a scaffold artifact that had split the step's
action clause into spurious scope rows.

**Reconciliation 2026-07-21 (post PR 246):** the parallel session's merged PR 246 shipped the same ask (`_store_writes` classification and bounded retry, `_SERVER_REQUEST_TIMEOUT_S` on the client, disk headroom guards). This branch's variant was removed in the origin/main merge; PR 246's shapes are canonical. The error_kind taxonomy moves to the jobs domain in P02.
