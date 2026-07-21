---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-21'
step_id: 'S07'
related:
  - "[[2026-07-14-storage-namespace-hygiene-plan]]"
---

# Integration-test the live daemon serving the cached survey after warmup and recomputing on fresh=true

## Scope

- `src/vaultspec_rag/tests/integration/test_storage_survey_service.py`

## Description

- Add three live-daemon tests to `src/vaultspec_rag/tests/integration/test_storage_survey_service.py`: freshness metadata present, cache served after warmup with stable `computed_at`, and `?fresh=true` recomputing then reseeding the cache
- Update `test_storage_survey_root_lookup_indexed_root` to query with `fresh=true`, matching the ADR's eventual-consistency contract for just-indexed roots

## Outcome

The warmup, cache, and recompute paths are exercised against a real daemon end to end.

## Notes

Run was deferred until the parallel session released the GPU (card was at 15.5/16.3 GB). Full module then passed: 11/11 in 409s, including the pre-existing envelope/root-lookup tests.
