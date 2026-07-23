---
tags:
  - '#exec'
  - '#index-job-backend-resilience'
date: '2026-07-23'
modified: '2026-07-23'
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

None.
