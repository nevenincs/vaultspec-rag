---
tags:
  - '#exec'
  - '#rag-index-performance'
date: '2026-06-02'
step_id: 'S01'
related:
  - "[[2026-06-02-rag-index-performance-plan]]"
---

# Extract a CPU-only chunk worker that reads, hashes, and chunks each file in one pass and never imports CUDA

## Scope

- `src/vaultspec_rag/indexer/_chunk_worker.py`

## Description

- Add a CPU-only worker module that reads a file once, computes the blake2b hash, and chunks it via tree-sitter AST (text-splitter fallback), returning a batched per-file result.
- Keep torch/CUDA off the worker import chain; a fresh-interpreter test guards that importing the worker never loads torch.

## Outcome

Chunk logic is picklable and shared by the serial and process-pool paths, so output is identical; the hash travels with the chunks so the tree is read once.

## Notes

Newline translation reproduces `Path.read_text` so chunk ids are byte-identical for CRLF files.
