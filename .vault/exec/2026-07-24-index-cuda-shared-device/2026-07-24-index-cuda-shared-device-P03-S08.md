---
tags:
  - '#exec'
  - '#index-cuda-shared-device'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:917335b20710dff90064cbee1c0e8fa112144f6308da4298539b161dca7a73be'
step_id: 'S08'
related:
  - "[[2026-07-24-index-cuda-shared-device-plan]]"
---

# prove the corpus-rejection guard fails when a runtime CUDA peak above the profile is re-admitted and rejects again if reinstated, both directions recorded

## Scope

- `src/vaultspec_rag/tests/test_job_resilience.py`

## Description

- Add `test_runtime_cuda_peak_is_not_a_corpus_rejection_dimension` to `src/vaultspec_rag/tests/test_job_resilience.py`: a `SupportMeasurement` whose `cuda_bytes` exceeds the active code profile's figure must return `None` from `exceeded_by` (admitted), while an over-limit `rss_bytes` measurement still rejects on `rss_bytes` (order preserved).

## Outcome

Corpus-rejection guard proven both directions in one uninterrupted sequence:

- RED: re-added `"cuda_bytes"` to the `exceeded_by` rejection tuple; the test failed on the intended assertion - `assert limits.exceeded_by(over_peak) is None` reported `('cuda_bytes', 12884901889, 12884901888) is None`.
- GREEN: removed the entry again; the test passed (1 passed).

## Notes

The test docstring names the mutation it catches (re-adding `cuda_bytes` to the rejection set).
