---
tags:
  - '#exec'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S15'
related:
  - "[[2026-07-29-encode-batch-adaptivity-plan]]"
---

# author degradation rate-baseline verdict tests proven able to fail when the baseline input is removed

## Scope

- `src/vaultspec_rag/tests/test_jobs_degradation.py`

## Description

- add `TestRateBaselineVerdict` to `src/vaultspec_rag/tests/test_jobs_degradation.py` pinning the degraded verdict against a replayed throughput collapse
- add `TestEncodeBudgetRendering` and `TestThroughputRendering` to `src/vaultspec_rag/tests/test_jobs_degradation_display.py` covering the presentation shipped one step earlier

## Outcome

Commit `e6d4d6f6`. Gates each exit 0; pytest 92 passed on named files plus 130 across the display, progress-rate, lifecycle, machine-pressure, and eta suites. Both guards proven able to fail on their named assertions (verdict input neutralized; summary part dropped) and pass restored; mutations documented in test comments.

## Notes

The display test file was added beyond the row's named file because the rendering step shipped without coverage.
