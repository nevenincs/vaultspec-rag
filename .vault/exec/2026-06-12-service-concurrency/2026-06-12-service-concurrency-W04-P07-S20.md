---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-07-27'
step_id: 'S20'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---
# Introduce env-tunable search and index capacity limiters replacing shared default thread-pool usage

## Description

### Scope

- `src/vaultspec_rag/server`

- Add `concurrency.py` with lazy, env-tunable capacity limiters: search
  pool (default 16) and index-job pool (default 4), plus limiter_stats().
- Wire the search route, both background reindex jobs, and both watcher
  reindex paths onto their limiters.

## Outcome

Index jobs can no longer exhaust the worker threads that serve searches;
saturation beyond a limiter queues callers instead of piling threads.

## Notes

Evidence gap: the original record contains no Notes section with authored incident, deferred-work, or follow-up evidence.
