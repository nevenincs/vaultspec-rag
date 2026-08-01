---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:d47e58ff471bb8ddc806298cdd712d203659f7a976b61cf8b6550641f7ce54a3'
step_id: 'S34'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Include bounded resilience rollups in service health without loading torch on the reporting path

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Confirm the service health payload carries a bounded latest-resilience rollup
  projected from the canonical snapshot
  (`src/vaultspec_rag/server/_lifespan.py:764`).
- Confirm the health reporting path loads no torch
  (`src/vaultspec_rag/server/_lifespan.py`).

## Outcome

Service health includes a bounded resilience rollup and reaches it without
touching torch, which are the two properties this step requires. The
implementation was already committed ahead of this plan's execute phase, so this
record confirms it against the contract rather than claiming to have built it.

The rollup is bounded: the health builder selects the single latest job record
carrying a resilience snapshot and projects it, rather than emitting the whole
job history, so the health payload grows with the number of dependencies it
reports, not with how many jobs the daemon has ever run. That bounded-view
discipline is the same one the operator surfaces follow.

The torch-free property was confirmed directly: the health module names torch
nowhere at all. That matters because health is a liveness probe that must answer
on a host where the GPU stack may be absent or already saturated; a reporting
path that imported torch to describe a job's CUDA high-water would defeat its
own purpose. The resilience numbers it reports are read from the canonical
snapshot, which recorded them when the job ran, so health re-reads state rather
than re-measuring it.

## Notes

Verified and recorded, not executed here - the rollup was committed before this
plan's execute phase reached the step.

The health file carries a small unrelated uncommitted change owned by another
effort. It was deliberately not touched: this step is a confirmation, so nothing
in the file needed editing, which also means the stray change is not swept into
any commit this step produces. It is flagged for its owner to reconcile
separately.

One consistency point carries forward to the verification step that checks the
jobs, health, and CLI surfaces expose identical resilience state. The response
shaping rounds its memory and duration measures to operator precision while this
health rollup projects the snapshot at full precision, so the two report the
same state but not byte-identical numbers. That difference is semantic
equivalence, not disagreement, and the verify step must treat it as such or the
health rollup should round to match; it is named here so it is met deliberately.
