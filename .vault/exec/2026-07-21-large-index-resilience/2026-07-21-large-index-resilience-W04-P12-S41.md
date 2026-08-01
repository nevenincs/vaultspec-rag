---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:a4867f8f52a99562ded789c700694f4ef2773bff5b0714cfd0889d8cebeda31a'
step_id: 'S41'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Measure source bytes, files, generated chunks, and weighted units without materializing the corpus

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Accumulate admitted source-file and source-byte dimensions during policy discovery.
- Carry exact full and scoped measurements in immutable preflight authorities.
- Accumulate generated chunks and conservative weighted bytes as bounded file segments are produced.
- Reject the first exceeded runtime dimension before its segment enters the GPU queue.

## Outcome

Code workloads expose exact source dimensions before execution and exact generated dimensions during bounded production. Measurement retains only counters plus the active segment; it never materializes source contents or a corpus-wide chunk collection.

## Notes

Both full and scoped discovery count only paths admitted to the code domain. Runtime measurement includes already-confirmed replay segments so the support contract describes the complete generated workload rather than only work remaining after restart.
