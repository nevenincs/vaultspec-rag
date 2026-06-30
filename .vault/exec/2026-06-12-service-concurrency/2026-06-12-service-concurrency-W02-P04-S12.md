---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-06-30'
step_id: 'S12'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Re-run the quality benchmarks to validate contextual embeddings and record deltas

## Scope

- `src/vaultspec_rag/tests/benchmarks`

## Description

- Re-run the quality harness with contextual code-chunk headers and
  per-surface query instructions active (shared run with the rerank step).

## Outcome

8/8 probes, 100% precision - no relevance regression from the embed-input
changes; the long-document tail-retrieval gain is separately proven by the
chunking integration tests. The harness ran while three concurrent index jobs
saturated the GPU, doubling as an adversarial co-load sample.

## Notes
