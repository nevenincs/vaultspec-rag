---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-07-27'
body_hash: 'sha256:daee8c11ed71ed84c1adb8c0c5129a1f58ca0ea382cd88e10bf502871269b0dc'
step_id: 'S21'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Move the cold ensure-watcher peek and log reads off the event loop

## Description

### Scope

- `src/vaultspec_rag/server/_watcher.py`

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

Evidence gap: the original record contains no Notes section with authored incident, deferred-work, or follow-up evidence.
