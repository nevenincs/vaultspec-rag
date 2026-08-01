---
tags:
  - '#exec'
  - '#rag-index-performance'
date: '2026-06-02'
modified: '2026-06-30'
body_hash: 'sha256:5a5767d2a843d7416182c33b9464df3debf9829942e9474d51d85c6f5251582a'
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
