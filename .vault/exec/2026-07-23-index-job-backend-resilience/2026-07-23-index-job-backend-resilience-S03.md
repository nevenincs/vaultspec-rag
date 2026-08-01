---
tags:
  - '#exec'
  - '#index-job-backend-resilience'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:9581c12c6a4a43f6856859f8b817b14efd253ef481a67b2bd88e9c55879402c2'
step_id: 'S03'
related:
  - "[[2026-07-23-index-job-backend-resilience-plan]]"
---

# Run the read operations (count, scroll, retrieve) under the bounded retry

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Wrapped the three point-count methods (vault, code, document) in `_retried`.
- Added `_scroll` and `_retrieve` helpers mirroring the client signatures and running under `_retried`.
- Routed all six `scroll` call sites and both `retrieve` call sites through them.

## Outcome

The reads an index job performs before its first write - counting points and scrolling existing chunk ids for changed files - now survive a transient backend refusal. A scroll or a retrieve is a pure query, so replaying an attempt that never reached the backend is safe.

One read is deliberately left unwrapped: the count inside the id-scan page-limit helper is reached only in local mode (server mode returns a fixed page size before it) and already carries its own fallback, so wrapping it would add retry to a path that cannot see a refused connection.

## Notes

Code review found the helpers were discarding the retry's admitted per-attempt timeout (the lambdas ignored it) even though the count, scroll, retrieve, delete, and payload-index client calls all accept a timeout. That made the retry's clamp inert and left each attempt bounded only by the client-level default. Every such call now receives the admitted value.

Also recorded from review: the interactive search reads in the search mixin deliberately stay single-shot rather than routing through this retry, because a user-facing query should fail fast and fall back instead of spending backoff. That divergence was previously silent and is now stated at the call site.
