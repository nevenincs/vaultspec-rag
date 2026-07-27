---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-07-27'
step_id: 'S15'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Narrow gpu_lock holds to model forward calls only across the search encode and rerank paths

## Description

### Scope

- `src/vaultspec_rag/search/_searcher.py`

- Hold the GPU lock only across model forward calls: rerank score
  conversion moved after release; query-cache hits skip the lock entirely;
  encode and rerank pair preparation already ran outside.

## Outcome

GPU lock hold per request is now bounded by forward-pass time alone.

## Notes

Evidence gap: the original record contains no Notes section with authored incident, deferred-work, or follow-up evidence.
