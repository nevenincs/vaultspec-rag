---
tags:
  - '#exec'
  - '#index-gpu-pipeline'
date: '2026-06-02'
modified: '2026-06-30'
step_id: 'S01'
related:
  - "[[2026-06-02-index-gpu-pipeline-plan]]"
---

# Add a bounded-queue feeder plus a single dedicated GPU consumer thread that owns the gpu_lock and runs dense then sparse encoding, replacing the inline drain

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Extract a shared `_encode_accumulated` drainer that encodes + upserts full slices and updates the shared `new_ids`/`total`.
- Add a single dedicated GPU consumer thread that drains a bounded `queue.Queue`, owns the `gpu_lock`, and runs dense then sparse encoding per batch.
- Make the main thread the producer that drains the spawn pool and feeds completed chunk lists onto the queue (the queue maxsize is the backpressure + memory bound).

## Outcome

The GPU consumer runs concurrently with CPU chunking (the only overlap that exists on one GPU); the GPU no longer idles during pool bookkeeping.

## Notes

Replaces the prior interleaved orchestrator per the index-gpu-pipeline ADR; this is the DataLoader producer/consumer pattern.
