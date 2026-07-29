---
tags:
  - '#exec'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S12'
related:
  - "[[2026-07-29-encode-batch-adaptivity-plan]]"
---

# add the rate-vs-self-baseline degraded input to the service degradation verdict with ceiling state attached as evidence

## Scope

- `src/vaultspec_rag/server/_routes_jobs.py`

## Description

- add the rate-vs-self-baseline input to `_job_degradation`: a running job whose recent rate falls below `RATE_COLLAPSE_RATIO = 0.25` of its run median reports degraded while forward-recency and stall verdicts stay unchanged

## Outcome

Commit `c4874d4b`. Gates each exit 0; pytest 87 passed. Threshold validated by replaying the incident's measured rates through the real registry: onset detected at 7x under median about two minutes into the collapse.

## Notes

`src/vaultspec_rag/_job_errors.py` was touched for the typed surface. One transient unrelated red during gating (a textual teardown timer race in the TUI suite under a forced test order) passed alone and in the standard invocation; nothing was committed red. Known limitation, flagged for the decision owner: once a collapsed regime occupies more than half the run, the median IS the collapsed rate and the verdict returns to healthy; closing that gap needs a different baseline statistic, which the ADR would have to amend.
