---
tags:
  - '#exec'
  - '#rag-index-performance'
date: '2026-06-02'
modified: '2026-06-02'
step_id: 'S04'
related:
  - "[[2026-06-02-rag-index-performance-plan]]"
---

# Decouple the code-path encode batch size, throttle the per-slice CUDA cache flush, and gate auto parallelism on total source bytes

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Decouple a code-path encode batch size (default 32), throttle the per-slice CUDA cache flush to every N slices, and gate auto parallelism on `index_parallel_min_bytes`.

## Outcome

Higher GPU throughput on short uniform code chunks; small/medium codebases stay serial and avoid spawn-pool overhead.

## Notes

The byte gate was added because a benchmark showed always-parallel regresses small trees.
