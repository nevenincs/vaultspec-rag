---
tags:
  - '#exec'
  - '#index-perf-hardening'
date: '2026-06-02'
modified: '2026-06-30'
step_id: 'S02'
related:
  - "[[2026-06-02-index-perf-hardening-plan]]"
---

# Swap the ThreadPoolExecutor chunk fan-out for a spawn-based ProcessPoolExecutor in the full-index path with an in-process serial fallback and a worker-count config knob

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Replace the GIL-bound ThreadPoolExecutor chunk fan-out with a spawn ProcessPoolExecutor in the full-index path.
- Add an in-process serial fallback and the `index_chunk_workers` config knob.

## Outcome

AST chunking scales across cores; tree-sitter holds the GIL for parse and traverse, so threads gave no speedup.

## Notes

Worker count later gated on total source bytes to avoid spawn-pool overhead on small trees.
