---
tags:
  - '#exec'
  - '#index-cuda-shared-device'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S07'
related:
  - "[[2026-07-24-index-cuda-shared-device-plan]]"
---

# prove the double-count guard fails when the ceiling reverts to bare free-minus-headroom and passes at baseline-plus-free-minus-headroom, both directions recorded

## Scope

- `src/vaultspec_rag/tests/test_config.py`

## Description

- Add `test_cuda_ceiling_auto_is_absolute_over_free_plus_resident_baseline` to `src/vaultspec_rag/tests/test_config.py`: patch total=16000/free=6000, baseline=5000, headroom=2048; assert a 3500 MiB net forward (inside free-headroom=3952) is admitted by a `MemoryBudget` built from the derived ceiling, assert ceiling == baseline+free-headroom (8952), and assert the idle-device clamp recovers total-headroom.
- Update the sibling auto/fallback test to patch `cuda_free_memory_mb -> None` and pass `baseline_mb`, and the override test to pass `baseline_mb`.

## Outcome

Double-count guard proven both directions in one uninterrupted sequence:

- RED: mutated the derivation to the bare form `min(free - headroom, total - headroom)`; the test failed on the intended assertion - the legitimate 3500 MiB net forward was falsely rejected with `JobError: cuda_memory_ceiling: CUDA allocated high-water above the 5000.0 MiB resident baseline 3500.0 MiB exceeded the 0.0 MiB ceiling at net forward within free memory`.
- GREEN: restored `baseline_mb + free - headroom`; the test passed (1 passed).

## Notes

The test comment names the mutation it catches (revert to bare free-minus-headroom) so the assertion is not loosened as over-specific later.
