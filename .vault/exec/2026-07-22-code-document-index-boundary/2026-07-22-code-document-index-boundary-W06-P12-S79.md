---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S79'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Generate a separately named document workload with measured source, extracted, chunk, queue, RSS, and CUDA dimensions

## Scope

- `src/vaultspec_rag/tests/benchmarks/bench_document_index_resilience.py`

## Description

- Generate marker-protected raw and extracted document inputs.
- Exercise production discovery, extraction, chunking, and weighted slicing.
- Report source, extracted, chunk, queue, RSS, and CUDA dimensions separately.

## Outcome

The document workload has a dedicated executable harness and machine-readable
measurement schema. Explicit route configuration owns every input; its layout
is only fixture organization and carries no admission semantics.

## Notes

Scoped Ruff and Ty checks passed. A unique marker-owned root completed the
prepare-only CPU boundary with the requested file and byte counts. The measured
production run is serialized with the phase GPU boundary.
