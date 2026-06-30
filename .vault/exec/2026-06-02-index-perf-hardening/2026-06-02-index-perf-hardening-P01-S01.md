---
tags:
  - '#exec'
  - '#index-perf-hardening'
date: '2026-06-02'
modified: '2026-06-30'
step_id: 'S01'
related:
  - "[[2026-06-02-index-perf-hardening-plan]]"
---

# Extract a module-level chunk worker plus a pool initializer that builds the per-language parser once per worker and decodes source once per file

## Scope

- `src/vaultspec_rag/indexer/_ast_chunker.py`

## Description

- Extract the chunk logic into a new CPU-only worker module with a per-worker reused chunker.
- Keep the worker free of torch/CUDA imports so spawn workers never initialise CUDA.

## Outcome

Chunking logic is picklable and shared by the serial and process-pool paths, guaranteeing identical output.

## Notes

Later folded hashing into the same worker for single-read I/O.
