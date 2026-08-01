---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:dced78229309c5a94e07e0fb0e97e3bc994e859676543e68ef848c52e0738ded'
step_id: 'S35'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Exercise a real watcher and shutdown lifecycle proving dirtiness coalescing, replacement scheduling, separate watcher control, and safe store closure using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/tests/integration/test_service_job_control_e2e.py`

## Description

- Start the real server watcher and watchfiles intake for one project.
- Pause a watcher-owned attempt at the production writer boundary.
- Coalesce later dirtiness under the same paused logical job and resume it.
- Cancel a distinct generation and require delayed replacement convergence.
- Stop watcher intake independently and await its complete owner drain.
- Close the project store only after manager and lease ownership reach zero.

## Outcome

The combined watcher and shutdown lifecycle passes. Pause retained one logical
job while a second change accumulated, resume converged both paths, cancellation
kept dirtiness durable, and a distinct delayed replacement indexed both later
paths. Explicit watcher stop removed intake state and joined cleanup before the
registry safely evicted the unleased store. Independent review passed with no
findings.

## Notes

The first focused run exposed a test predicate that could select the earlier
successful generation. The predicate now excludes both earlier identifiers and
requires the actual replacement. The corrected focused run passed in 19.37
seconds. Ruff and BasedPyright pass. No doubles or monkeypatching were used.
