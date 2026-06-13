---
tags:
  - '#exec'
  - '#rag-index-performance'
date: '2026-06-02'
modified: '2026-06-02'
step_id: 'S05'
related:
  - "[[2026-06-02-rag-index-performance-plan]]"
---

# Add real-GPU parity and consumer-failure tests plus a chunk-stage benchmark, and validate the integration suite on GPU

## Scope

- `src/vaultspec_rag/tests/integration/`

## Description

- Add real-GPU parity (parallel == serial chunk ids + metadata) and consumer-failure (real dimension mismatch propagates without hanging) tests, plus a CPU-only chunk-stage benchmark.
- Validate the codebase and indexer integration suites on real GPU.

## Outcome

Parity and fail-loud shutdown locked down with no mocks; integration suites green on GPU; benchmark shows 1.9x (real 17,872 files) to 3.6x (heavy synthetic 8,000 files), parity OK.

## Notes

A clean end-to-end chunk+embed number is contended by the resident GPU service; documented as a manual step with the service stopped.
