---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S24'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---




# persist an active-jobs snapshot and mark jobs from a prior daemon life as interrupted at startup so killed jobs never vanish from server jobs

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

Running jobs now persist a bounded snapshot (`jobs-active.json` in the
status dir, atomic write) on start, finish, and step change; daemon
startup restores a prior life's running jobs as phase `interrupted` with
their last progress, start time, and initiator attribution, then consumes
the snapshot so a second restart restores nothing. The `Phase` literal
gains `interrupted`; `reset()` deliberately leaves the file so tests can
simulate daemon death.

## Outcome

Committed as the interrupted-jobs commit; restore semantics covered by
`TestInterruptedJobRestore`.

## Notes

Step-change persistence keeps write churn to a handful of writes per run
while restored progress stays meaningful.
