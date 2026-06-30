---
tags:
  - '#exec'
  - '#rag-index-performance'
date: '2026-06-02'
modified: '2026-06-30'
step_id: 'S02'
related:
  - "[[2026-06-02-rag-index-performance-plan]]"
---

# Replace the ThreadPoolExecutor fan-out with a spawn ProcessPoolExecutor across full, incremental, and scoped paths with a serial fallback and a worker-count knob

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Replace the GIL-bound ThreadPoolExecutor fan-out with a spawn ProcessPoolExecutor in the full, incremental, and scoped paths.
- Add a serial in-process fallback and the `index_chunk_workers` knob.

## Outcome

AST chunking scales across cores; tree-sitter holds the GIL for parse and traverse, so threads gave no speedup.

## Notes

None.
