---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-07-27'
step_id: 'S16'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---
# Add a thread-safe LRU query-embedding cache keyed by surface and cleaned query text

## Description

### Scope

- `src/vaultspec_rag/embeddings.py`

- Add QueryEmbeddingCache, a thread-safe LRU (128 entries) keyed by
  (surface, cleaned query text) holding dense + sparse query vectors;
  wired into `_encode_query` ahead of the GPU section.

## Outcome

Repeat queries skip both encoder forward passes and the GPU lock.
Eviction, surface keying, and concurrent access covered by unit tests.

## Notes

Evidence gap: the original record contains no Notes section with authored incident, deferred-work, or follow-up evidence.
