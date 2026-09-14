---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-25'
modified: '2026-09-14'
body_hash: 'sha256:8fba4b70b1dbaac757514e6668af628a9ab86a59afadee49d3ad3899a4c99a14'
step_id: 'S09'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---
# re-tune the CUDA cache flush cadence under overlap and record the measured effect

## Scope

- `src/vaultspec_rag/config/_settings.py`
- `measured run`

## Description

- Verify the production allocator high-water telemetry for vault runs before considering a default change.
- Compare the shipped cadence of one slice with the candidate cadence of eight under an exclusive device window.
- Require alternating arms on the same corpus, with wall time, work time, allocated and reserved peaks, ceiling distance, and OOM events recorded for every arm.

## Outcome

REPORT-BLOCKED. The production telemetry prerequisite is resolved: vault runs now register the shared forward-peak recorder, sample memory around the run, retain the immutable budget snapshot, and project peak allocated and reserved memory into job resilience without inventing a support ceiling.

The controlled A/B is still absent, so the defaults remain unchanged at one slice for vault and document indexing. A prior attempt produced one quiet cadence-one arm at 131.9 seconds with 3,626 MiB peak reserved and 3,572 MiB peak allocated. Its cadence-eight arm overlapped a daemon code index job and watcher restart, ran for more than fifteen minutes, and was killed unfinished. That arm is discarded: device contention and cadence changed together, so no delta is attributable to cadence.

The current attempt also found no valid window. Before measurement, the device reported 13,691 MiB used and 100 percent utilization with two watcher jobs active. The supported cooperative service pause then returned `drain_timed_out` with five compute tickets held. The pause was immediately aborted through service resume, restoring admissions. No cadence arm was launched and no timing claim was made.

Acceptance remains unchanged: raise a default only after same-corpus, order-reversed arms complete under an exclusive device window and show no material reserved-memory climb toward the effective ceiling and no OOM-ladder event. Until then, historical per-slice flushing is the safe behavior.

## Notes

The transport-independent gRPC measurement belongs to a separate decision and is not part of this Step. For a future cadence run, ensure vector reuse is disabled so the corpus is actually encoded, establish service quiescence with a completed compute-ticket drain, confirm the active job list is empty immediately before and after every arm, and discard any arm that overlaps another encoder.
