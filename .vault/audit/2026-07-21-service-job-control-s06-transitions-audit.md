---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` audit: `service-job-control audit: W01.P02.S06 deterministic job transitions`

## Scope

Independent concurrency, ownership, state-machine, compatibility, and safety review of the
final `W01.P02.S06` transition implementation in `jobs.py`.

## Findings

### queued-post-pause-claim | high | A stale dispatcher could attach after pause committed

The initial first-claim path did not revalidate the canonical queued and desired-running
state under the manager lock. A dispatcher selected before a concurrent pause could therefore
attach a task after the resource had become paused. The revision makes first claim conditional
on active `QUEUED` plus desired `RUNNING` within the same atomic manager operation.

### stale-attempt-ownership | high | An obsolete generation could mutate replacement work

The initial ownership API keyed task and worker mutations by job ID without requiring the
current attempt generation at every boundary. A delayed attempt could seize, clear, or release
the runtime of a later retry. The revision requires exact attempt validation on claim and
release and exact task-plus-attempt validation for worker state and running acknowledgement.

Final review found no unresolved critical, high, medium, or low findings. Exact ownership,
pause and resume delivery, absorbing cancellation, release gates, terminal immutability,
retry, deletion, deduplication, admission, and bounded history probes passed. Forty-nine
focused tests, two 200-iteration real threaded race probes, Ruff, ty, BasedPyright, and diff
checks passed.

Status: **PASS** after revision.

## Recommendations

Keep persistence and restart recovery keyed by both logical job ID and attempt lineage, and
exercise the same ownership checks through the public adapters in later Steps.
