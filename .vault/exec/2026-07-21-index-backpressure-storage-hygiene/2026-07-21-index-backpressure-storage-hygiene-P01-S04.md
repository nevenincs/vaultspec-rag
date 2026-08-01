---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:c7cbc1d9651d93baa43dabd1303dc4b541490fa72e1834a6bc61846089436883'
step_id: 'S04'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# add unit tests for write-error classification, disk_full non-retryability, and the bounded encode ladder

## Scope

- `src/vaultspec_rag/tests/`

## Description

New `test_store_write_unit.py`: a classification table test for
`_classify_write_error` (errno 28, WAL and optimizer space messages,
timeout, connection-refused, fallback) and a `_ScriptedClient` +
store-shell harness proving disk_full and rejected fail on first sight,
transient timeouts retry within the configured budget then succeed or
raise `StorageWriteError` with the kind attached, and the cause chain
preserves the original exception.

## Outcome

Committed as `test(store): write-error classification and bounded-retry contract (#242)`; 10 tests green with zero backoff via env knobs.

## Notes

The store shell is built with `object.__new__` because `VaultStore. __init__` opens a real backend; the write path only touches
`_server_mode`, `_client`, and the point-lock plumbing.

**Reconciliation 2026-07-21 (post PR 246):** the parallel session's merged PR 246 shipped the same ask (`_store_writes` classification and bounded retry, `_SERVER_REQUEST_TIMEOUT_S` on the client, disk headroom guards). This branch's variant was removed in the origin/main merge; PR 246's shapes are canonical. `test_store_write_unit.py` was deleted; PR 246's `test_store_writes.py` is the canonical coverage.
