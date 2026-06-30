---
tags:
  - '#exec'
  - '#index-perf-hardening'
date: '2026-06-02'
modified: '2026-06-30'
step_id: 'S06'
related:
  - "[[2026-06-02-index-perf-hardening-plan]]"
---

# Fold file hashing into the single worker read so the tree is read once instead of twice

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Fold file hashing into the chunk worker so the full index reads each file once; the hash matches `hashlib.file_digest`.
- Add the `index_parallel_min_bytes` byte gate so auto mode only parallelises above the spawn/serial crossover.

## Outcome

The full-index tree is read once; small/medium codebases stay serial and avoid spawn overhead.

## Notes

Worker newline translation reproduces `Path.read_text` so chunk ids are byte-identical for CRLF files.
