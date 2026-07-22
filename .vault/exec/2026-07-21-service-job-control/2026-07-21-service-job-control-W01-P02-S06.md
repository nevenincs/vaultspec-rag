---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S06'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Implement revisioned pause, resume, cancellation, retry, terminal deletion, first-terminal-writer-wins, and deterministic races using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- Add revisioned pause, resume, cancellation, retry, and terminal-deletion commands.
- Bind runtime ownership and observed-state acknowledgements to the exact task and attempt.
- Make cancellation absorbing and protect terminal state with first-terminal-writer-wins.
- Gate retry and deletion on complete runtime and execution-resource release.
- Serialize dispatch, control delivery, withdrawal, completion, and replacement races.

## Outcome

The durable job manager now exposes deterministic lifecycle transitions over immutable
snapshots. Stale revisions, tasks, and attempt generations cannot mutate replacement work;
pause withdrawal and delivery have one atomic ordering; cancellation cannot be reversed; and
terminal completion, retry, and deletion preserve resource-release and retention invariants.

## Notes

Independent review found two High defects: a stale dispatcher could claim queued work after a
pause committed, and a stale attempt generation could seize or release a replacement runtime.
Both were corrected with atomic dispatch-state gating and exact task-plus-attempt ownership.
Final review found no unresolved findings at any severity. Forty-nine focused tests, exact
production probes, two 200-iteration threaded race probes, Ruff, ty, BasedPyright, and diff
checks passed.

The legacy live-service registry tests were also attempted. Their 49 unit assertions passed,
but the live fixture stopped before job assertions because the Windows Qdrant process-image
witness exhausted its bounded inspection path. That fixture-level failure is separate from
this Step and remains visible for follow-up verification.
