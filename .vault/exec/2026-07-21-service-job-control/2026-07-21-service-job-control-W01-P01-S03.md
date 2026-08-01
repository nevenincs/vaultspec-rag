---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:069a7178badc17c8f98d301e08c9fdeb1357fc1bd396c5ea6871217bddc700be'
step_id: 'S03'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Verify control primitives and configuration through imported production behavior using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/tests/test_job_control_unit.py`

## Description

- Exercise cross-thread pause delivery through nested protected spans and their outer safe edge.
- Verify reversible pause, absorbing repeated cancellation, and protected-entry delivery.
- Preserve application failures while leaving cooperative control pending for the next checkpoint.
- Verify the runtime protocol and no-control implementation through imported production objects.
- Resolve defaults, environment overrides, and invalid settings in isolated Python processes.

## Outcome

Fifteen imported-production tests now prove the S01 and S02 contracts without test doubles or
runtime mutation. The focused suite passes, as do Ruff formatting and lint, ty, and strict
BasedPyright checks.

## Notes

Environment-sensitive cases execute in fresh child interpreters with only the two job-control
variables isolated. Job-manager behavior remains assigned to later plan Steps. The test run
reported only pre-existing `pytest-durations` deprecation warnings.
