---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-06-12'
step_id: 'S21'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Move the cold ensure-watcher peek and log reads off the event loop

## Scope

- `src/vaultspec_rag/server/_watcher.py`

## Description

- Add `_ensure_watcher_soon`: per-request callers (search/reindex routes)
  schedule watcher ensure as a background task that warms the project slot
  on a worker thread; explicit watcher-control routes keep the
  deterministic synchronous path.
- Dispatch rotated-set service log reads off the event loop in both log
  routes.

## Outcome

The 50-200ms cold project peek and multi-megabyte log reads no longer
stall every in-flight request on the loop thread.

## Notes
