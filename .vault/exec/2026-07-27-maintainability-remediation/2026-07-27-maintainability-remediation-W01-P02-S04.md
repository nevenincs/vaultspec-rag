---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-07-27'
step_id: 'S04'
related:
  - "[[2026-07-27-maintainability-remediation-plan]]"
---

# Move job-manager value and execution responsibilities into concrete owners and migrate consumers

## Scope

- `src/vaultspec_rag/job_manager.py`

## Description

- Convert the job-manager monolith into direct concrete owners for models,
  execution, records, progress, control, persistence, and state typing.
- Retain `JobManager` as the aggregate state owner and migrate production and
  test consumers to the concrete modules.
- Add an unknown-attribute regression test so typing support cannot mask a
  misspelled runtime attribute.

## Outcome

The former `job_manager.py` module is deleted. The eight replacement modules
all have maintainability scores above the former 0.00 floor; the lowest is
12.75. The focused real-behavior suite reports 106 passed. Lint, formatting,
and strict type checks pass for the package and direct consumers.

## Notes

The shared worktree includes concurrent changes to direct consumers, so no
mixed-scope commit was created. The verified code and this record remain
available for the owning change set to commit coherently.
