---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S25'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Update service health rollups so paused and transitional jobs remain visible without false stall signals using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Merge bounded canonical manager jobs with legacy-only service activity.
- Derive health counts from the shared canonical job-summary transform.
- Expose queued, paused, transitional, active, stalled, control-pending, and
  per-state rollups.
- Preserve the most recent structured failure classification.
- Verify paused work remains visible without being classified as stalled.

## Outcome

The health response now represents every canonical nonterminal lifecycle state
without treating paused or queued work as failed progress. Transitional work is
visible independently and becomes stalled only through the shared pending
control-age rule.

One focused production-behavior test passes. Ruff, Ruff format, and Ty pass for
the changed health and test modules.

Independent review found two medium-severity issues. Global newest-failure
selection and isolated manager persistence now address both; final Ruff and Ty
checks pass.

## Notes

The rollup remains bounded by the canonical terminal-history and legacy
activity limits. No test double, skipped test, destructive Git operation, or
data loss occurred.
