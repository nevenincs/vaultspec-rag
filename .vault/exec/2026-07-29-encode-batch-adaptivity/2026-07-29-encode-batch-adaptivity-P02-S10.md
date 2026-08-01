---
tags:
  - '#exec'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
body_hash: 'sha256:74fa75a2edb42cefde401217a4fb4f8526cd225ce2b78c135edaf6c4ee11a49c'
step_id: 'S10'
related:
  - "[[2026-07-29-encode-batch-adaptivity-plan]]"
---

# carry the per-job OOM counter and encode budget state on the job record runtime block

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- carry the per-job encode OOM counter and encode budget state (token budget, last bucket size) on the job record runtime block in `src/vaultspec_rag/jobs.py`, absent until first reported and null-safe throughout
- add the producer seams `JobProgressReporter.encode_budget_planned` and `JobProgressReporter.encode_oom`, mirroring the forward-report helpers
- establish a bounded run-spanning progress-rate history (120 slots, 30 s spacing, 8-observation minimum) and `progress_rate_baseline()`, derived from samples the reporter already takes

## Outcome

Commit `9e6ccedd` on branch `encode-batch-adaptivity-p02`. Gates each exit 0; pytest 87 passed on named files plus 51 on the progress-rate and lifecycle suites.

## Notes

The run baseline landed here rather than in the projection step: the existing 16-sample rate window refills with a collapsed rate within seconds and is structurally unable to see a collapse; no new sampler or thread was added.
