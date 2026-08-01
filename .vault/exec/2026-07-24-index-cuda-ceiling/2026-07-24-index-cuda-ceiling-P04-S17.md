---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:1941602dd71e30c07e12103c4855819117eb01340e0c0c25a512d2b8be936c7c'
step_id: 'S17'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# prove the double-count guard fails when the baseline is subtracted from only one side of the ceiling comparison, recording both directions

## Scope

- `src/vaultspec_rag/tests/test_config.py`

## Description

- Add `test_cuda_ceiling_comparison_is_baseline_consistent` to `src/vaultspec_rag/tests/test_config.py`: a peak between (ceiling - baseline) and the ceiling must be admitted; a peak just above the ceiling must be rejected, with the baseline-relative measure named in the detail.
- Prove both single-side mutations fail the guard, as one uninterrupted sequence per mutation.

## Outcome

Both directions observed and recorded:

- Ceiling-only subtraction RED: with the baseline removed from the peak side only, the admitted-path observation (900 MiB, inside the true 1000 MiB ceiling) was wrongly rejected - `cuda_memory_ceiling: ... 900.0 MiB exceeded the 600.0 MiB ceiling` - the exact covert tightening the guard exists to catch. Restored: passed.
- Peak-only subtraction RED: with the baseline removed from the ceiling side only, the over-ceiling observation (1050 MiB) was wrongly admitted - `Failed: DID NOT RAISE JobError`. Restored: passed, full modules 132/132 green.

## Notes

None.
