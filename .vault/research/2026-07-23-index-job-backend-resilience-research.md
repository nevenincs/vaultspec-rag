---
tags:
  - '#research'
  - '#index-job-backend-resilience'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:2c1d4feaab8c67cc33cfebbf0dd1a7fe7f17a03071907a14b707a5a4a2d05dc8'
related: []
---

# `index-job-backend-resilience` research: `connect and read paths bypass the bounded store retry`

Background code, vault, and document index-update jobs failed for hours with `[WinError 10061] No connection could be made because the target machine actively refused it` - a connect-time refusal meaning nothing was listening on the managed vector store's port at that instant. A separate job was `interrupted` because `the service stopped before the attempt acknowledged`. The question is why a momentary backend unavailability turns a background index job into a hard, non-retried failure when a bounded transient retry already exists. The evidence shows the retry covers exactly one store operation - the upsert write - and that every other store call a job makes (connection establishment, collection ensure, and all reads) is a single-shot network call that dies immediately on a refused or restarting backend.

## Findings

### The bounded retry wraps only the upsert write

The store-write hardening classifies a failure as unrecoverable (storage exhaustion) versus transient and retries transient failures with capped exponential backoff, in `src/vaultspec_rag/_store_writes.py`. A refused connection is transient: `classify_write_error` returns `"transient"` for anything that is not `ENOSPC` or a disk-full WAL marker (`src/vaultspec_rag/_store_writes.py:83`), so connection-refused is explicitly retry-eligible. But the only call site of `run_write_with_retry` in the entire store is the upsert, at `src/vaultspec_rag/store.py:967`. No other store operation is wrapped.

### Every non-write store call is single-shot

In `src/vaultspec_rag/store.py`, `collection_exists` (called from `ensure_code_table` at `:703`, plus `:488`, `:555`, `:563`, `:571`, `:637`, `:734`), `count` (`:299`, `:1421`, `:1431`, `:1437`), `scroll` (`:1122`, `:1224`, `:1290`, `:1347`, `:1396`, `:1519`), `retrieve` (`:1324`, `:1458`), `delete` (`:1003`, `:1031`, `:1046`, `:1060`, `:1160`), `create_collection` (`:506`), and `create_payload_index` (`:648` onward) all call the client directly with no retry. Each raises immediately if the backend refuses the connection.

### A code-index job touches ensure and read paths before its first retried write

An index update calls `ensure_code_table` (which runs `collection_exists` and possibly `create_payload_index`) and reads existing point ids for changed files via `scroll`/`count` before it ever reaches the retried upsert. So during any window in which the managed store is not listening - a restart, a corrupt-collection quarantine cycle, or a stale runner pointed at a backend that is no longer there - the job fails on the ensure or read call, never reaching the code path that would have retried. This matches the observed failure signature: the refusal arrives before completion count advances, and the whole job fails rather than waiting out a brief blip.

### The qdrant client connects lazily, so refusal surfaces on first request

The server-mode client is constructed in `src/vaultspec_rag/store.py:232` with an explicit request timeout but performs no connection at construction; the HTTP client connects on first request. Therefore the refusal never surfaces in `__init__` - it surfaces on the first actual operation, which for an index job is an ensure or a read, confirming those are the paths that must tolerate a transient refusal.

### One observed trigger: orphaned daemons pointed at a dead backend

A companion investigation into service-orphan reaping (the orphaned-daemon accumulation tracked as issue #256) is one concrete way a runner ends up issuing store calls against a port nothing is listening on: a stale job runner in a daemon whose backend has gone. This is a trigger, not the defect. The resilience gap - unretried connect/ensure/read paths - makes ANY transient unavailability window (restart, quarantine self-heal, orphan) a hard failure, so the fix is independent of and must not depend on the orphan-reaping work; it is cross-linked here only to record the observed cause.

### Option space

The gap can be closed by generalising the existing transient-retry policy from write-only to all store operations, by adding a connection-health gate that waits for the backend before a job runs, or by making the job runner catch-and-reschedule on `unavailable`. A connection gate alone does not cover a mid-job restart between operations; reschedule-on-unavailable duplicates backoff the store already knows how to do and loses in-run progress. Generalising the bounded retry reuses the proven classification and backoff and covers both first-operation and mid-run refusals. The idempotency of reads and ensure (both naturally repeatable) and of deletes (delete-by-id/by-filter is idempotent) means a bounded retry is safe for them; the ADR must confirm each wrapped operation is safe to replay and that the durable no-progress budget still bounds total wait.

### Not investigated

Whether qdrant-client exposes a built-in transport-level retry that could be configured instead of a wrapper (the existing pattern is an explicit wrapper, so consistency favours extending it; worth a brief confirmation during the ADR). Whether local (on-disk) mode needs the same treatment - a refused connection is a server-mode concept, so local mode is out of scope.

## Sources

- `src/vaultspec_rag/_store_writes.py:83` - `classify_write_error`, connection-refused is transient
- `src/vaultspec_rag/_store_writes.py` - `run_write_with_retry` bounded backoff policy
- `src/vaultspec_rag/store.py:967` - the sole `run_write_with_retry` call site (upsert)
- `src/vaultspec_rag/store.py:703` - `ensure_code_table` collection-exists, unretried
- `src/vaultspec_rag/store.py:232` - server-mode client construction, lazy connect
- `src/vaultspec_rag/_job_errors.py:174` - `unavailable` maps connection-refused for reporting
- issue #256 - orphaned-daemon accumulation, one observed trigger (not a dependency)
