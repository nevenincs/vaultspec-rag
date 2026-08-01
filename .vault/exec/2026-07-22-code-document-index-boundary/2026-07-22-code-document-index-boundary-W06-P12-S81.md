---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:c4254bbc432a99df9ac6312cf8f38abd2e153d5880bec8502db12d134792066b'
step_id: 'S81'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify bounded document completion, interruption, and resume with representative real formats, extractor processes, CUDA, and Qdrant

## Scope

- `src/vaultspec_rag/tests/benchmarks/bench_document_index_resilience.py`

## Description

- Run real direct decoding and out-of-process extraction under one bounded profile.
- Interrupt after the first storage-confirmed document unit.
- Resume the same generation through CUDA embedding and local Qdrant publication.

## Outcome

The named acceptance workload completed four files and ten chunks. It resumed
the interrupted generation from one confirmed unit to ten without replaying
confirmed work. Peak RSS was 1,693,052,928 bytes and peak CUDA reservation was
1,927,282,688 bytes.

## Notes

The first sparse run exposed an observation-timeout ordering defect in the
harness before cancellation was requested. The corrected dense acceptance run
completed in 35.7 seconds against real CUDA and local Qdrant; all resources
were released afterward.
