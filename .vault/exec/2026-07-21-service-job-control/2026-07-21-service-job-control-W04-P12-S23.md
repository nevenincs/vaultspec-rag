---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S23'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Extend job shaping, filtering, ordering, stall classification, control age, capabilities, and canonical state summaries using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/server/_routes_jobs.py`

## Description

- Shape canonical job snapshots while retaining legacy collection aliases.
- Derive source and project data from the canonical nested specification.
- Filter observed state, desired state, capability, source, trigger, prefix,
  age, failure, phase, and free text.
- Measure runtime and control ages at truthful lifecycle boundaries.
- Keep queued and paused work inert while aging pending transitions.
- Order actionable states before bounded terminal history.
- Summarize canonical states, desired states, capabilities, control latency,
  initiators, sources, triggers, users, stalls, and failures.
- Add focused imported-production coverage in
  `src/vaultspec_rag/tests/test_jobs_unit.py`.

## Outcome

Canonical `JobSnapshot.to_dict()` records now retain every stable field and
gain compatibility `phase`, `source`, and `trigger` values. Legacy watcher
records with progress step `queued` or `paused` project to the corresponding
canonical state instead of stale `running` state.

Paused runtime stops at its state-change boundary. Completed runtime stops at
`finished_at`. Pending transition age alone drives transitional stalls.
Capabilities remain manager-owned and determine controllability and retry
rollups. Stable ordering places transitions, running work, queued work, paused
work, actionable failures, cancellation, and success before unknown history.

All 9 focused `TestJobStallShaping` behavior tests pass. The combined
`test_jobs_unit.py`, `test_server_routes.py`, and
`test_service_jobs_progress.py` run passes 58 of 58 tests. PyCompile, Ruff,
Ruff format, Ty, BasedPyright,
cognitive complexity, nesting, Radon, Xenon, and diff hygiene pass. Maximum
cyclomatic complexity is grade C at 15, and the module average is grade A at
4.09. Independent review passed with no findings.

## Notes

No fake, mock, stub, patch, monkeypatch, skip, or expected-failure path was
introduced. A fresh-interpreter probe confirmed canonical shaping does not
load `torch`. Graphics processing unit (GPU)-backed tests were outside this
pure shaping step.

The Radon and Xenon analyses ran outside the project directory because the
command-line interface (CLI) configuration parser rejects percent tokens in
the project test logging format. Both analyses completed successfully.
`src/vaultspec_rag/server/_routes.py`, the `S24` route file, remained
untouched. No data was lost.
