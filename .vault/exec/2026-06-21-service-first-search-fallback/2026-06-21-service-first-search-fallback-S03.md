---
tags:
  - '#exec'
  - '#service-first-search-fallback'
date: '2026-06-21'
modified: '2026-06-21'
step_id: 'S03'
related:
  - "[[2026-06-21-service-first-search-fallback-plan]]"
---

# Bound any mandated local run with a wall-clock deadline that releases the store lock and exits non-zero on expiry

## Scope

- `src/vaultspec_rag/cli/_search.py`

## Description

- Add `_local_search_deadline` context manager wrapping the mandated in-process search with a daemon timer derived from `_get_search_timeout(timeout)`.
- Add `_abort_on_local_deadline` (timeout envelope to stderr, then `os._exit(124)`) so a wedged run cannot hang holding the index lock; process exit releases the lock.

## Outcome

Mandated local runs are wall-clock bounded; `on_timeout` is an injectable seam so the timer is testable without process exit.

## Notes

A native CUDA hang holding the GIL is bounded only by process kill, not the in-process watchdog; recorded as the decision's residual.
