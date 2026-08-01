---
tags:
  - '#exec'
  - '#index-gpu-pipeline'
date: '2026-06-02'
modified: '2026-06-30'
body_hash: 'sha256:135657626fe9010464f762d847a2c47662cb3b84473fd4a9e3946b94cdac09ae'
step_id: 'S05'
related:
  - "[[2026-06-02-index-gpu-pipeline-plan]]"
---

# Validate no regression on the real codebase end to end with the resident service stopped

## Scope

- `src/vaultspec_rag/tests/benchmarks/`

## Description

- Re-run the codebase integration suite and the pipeline tests on real GPU after the shutdown fix.

## Outcome

23 codebase + pipeline integration tests green on real GPU; no functional regression.

## Notes

A clean end-to-end chunk+embed wall-clock could not be obtained on the live machine: it contends with the resident RAG service for the single GPU. Documented as a manual step.
