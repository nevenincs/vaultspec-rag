---
tags:
  - '#exec'
  - '#index-perf-hardening'
date: '2026-06-02'
step_id: 'S04'
related:
  - "[[2026-06-02-index-perf-hardening-plan]]"
---

# Wire a bounded producer/consumer so process-pool chunk batches feed a single in-process GPU consumer that advances the reporter and preserves stale-purge and failure-safe rebuild semantics

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Wire a bounded producer/consumer so process-pool chunk batches feed the GPU encode/upsert, advancing the reporter from completed files and preserving stale-purge and failure-safe semantics.

## Outcome

Chunk and embed overlap; prepare-collection moved before the pipeline; meta sourced from the workers.

## Notes

This initial pipeline interleaved encode on the orchestrator thread; superseded by the index-gpu-pipeline dedicated GPU consumer thread.
