---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S19'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# add a test asserting a reserved high-water above the ceiling no longer fails a job while an allocated high-water above it still does

## Scope

- `src/vaultspec_rag/tests/test_job_resilience.py`

## Description

- Assert a reserved high-water above the ceiling is admitted (twice, with reserved reported on the snapshot) while an allocated high-water above the ceiling still raises the typed CUDA failure naming the allocated measure.

## Outcome

Tests `test_cuda_reserved_above_ceiling_is_diagnostic_not_enforced` and `test_low_configured_cuda_budget_returns_typed_failure` cover both directions of the enforcement split.

## Notes

Deviation from the plan's scoped file: both tests live beside the existing `MemoryBudget` policy tests in `src/vaultspec_rag/tests/test_config.py` rather than `test_job_resilience.py`, which exercises record serialization, not enforcement policy. The negative test's failure proof (reserved comparison temporarily reintroduced: RED `JobError: cuda_memory_ceiling ... reserved high-water 11.0 MiB exceeded the 3.0 MiB ceiling`, then GREEN) is recorded in the body of commit `29168706`.
