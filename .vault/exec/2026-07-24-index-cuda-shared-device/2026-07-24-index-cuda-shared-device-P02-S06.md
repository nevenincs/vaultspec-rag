---
tags:
  - '#exec'
  - '#index-cuda-shared-device'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S06'
related:
  - "[[2026-07-24-index-cuda-shared-device-plan]]"
---

# remove cuda_bytes from the code indexer corpus-dimension rejection while keeping the measured field and its JSON reporting

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Remove `cuda_bytes` from the rejection tuple in `SupportProfileLimits.exceeded_by` (`src/vaultspec_rag/index_profiles.py:89`), leaving the other dimensions' order and messages untouched.
- Keep the `cuda_bytes` measurement field on `SupportMeasurement`/`SupportProfileLimits`, its projection in `_record_resource_measurement` (`src/vaultspec_rag/indexer/_codebase_indexer.py`), and its JSON reporting (`index_support_profile_status`, `src/vaultspec_rag/server/_routes.py`).
- Update `test_profile_rejects_corpus_dimensions_structurally` in `src/vaultspec_rag/tests/test_index_profiles.py` to drop the now-removed cuda rejection case.
- Verify the document indexer needs no change: `_DocumentResourceBudget.reserve` rejects only chunks/weighted/extracted, and `_retain_snapshot` keeps `cuda_bytes` diagnostic-only.

## Outcome

A runtime CUDA peak above the profile `cuda_bytes` figure no longer refuses a code job as `corpus_limit_exceeded`; runtime CUDA demand is owned by the per-job ceiling, forward-peak capture, and OOM backoff. The two indexers now agree.

## Notes

The docstring on `exceeded_by` states the constraint directly (runtime peak is not a corpus dimension) rather than citing any record.
