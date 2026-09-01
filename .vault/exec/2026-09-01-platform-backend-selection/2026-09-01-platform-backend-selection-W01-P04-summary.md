---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:c525a6815b23ed2d3f38ef3ee1617680e61cf73bccc59dd7d4d65ea74af92d23'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---
# `platform-backend-selection` `W01.P04` summary

Migrated every production compute path from CUDA-specific loading to the canonical accelerator context.

## Description

Dense embedding, sparse embedding, reranking, search, indexing, service state, readiness, and bounded OOM recovery now dispatch through the selected CUDA or MPS backend. CUDA allocator controls remain CUDA-only; MPS cache and OOM behavior use the backend contract. Legacy `load_torch` production usage was removed and guarded.

## Verification

Compute-path, service, readiness, hygiene, and ADR regression suites passed, including deliberate mutation failures.
