---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:223383ace28f61374c91edcbf50b6001bdcd76130a1542e77ce4ce74912cec31'
step_id: 'S16'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# prove the cross-job contamination guard fails when enforcement reads the process-global counter and passes when it reads the captured peak, recording both directions

## Scope

- `src/vaultspec_rag/tests/test_job_resilience.py`

## Description

- Add `test_budget_enforces_captured_job_peak_not_process_global_counter` and `test_forward_peak_capture_routes_to_thread_recorder_and_keeps_maximum` to `src/vaultspec_rag/tests/test_job_resilience.py`.
- Prove both guards can fail, as one uninterrupted break/observe/restore/observe sequence per mutation.

## Outcome

Both directions observed and recorded:

- Contamination guard RED: with `sample`'s enforced peak re-pointed at the process-global reading, the test failed for the intended reason - `JobError: cuda_memory_ceiling: CUDA allocated high-water 9000.0 MiB exceeded the 1000.0 MiB ceiling at code producer queue wait`. Restored: 1 passed.
- Plumbing guard RED: with the recorder dispatch severed inside the capture bracket, the test failed on the intended assertion - `assert 0.0 == 321.5` (captured maximum never reached the budget). Restored: 1 passed.

The guard's live-measurement patch plays a sibling's mid-flight forward; the assertion is deliberately narrow so any re-pointing of the enforced peak at a process-wide counter trips it.

## Notes

None.
