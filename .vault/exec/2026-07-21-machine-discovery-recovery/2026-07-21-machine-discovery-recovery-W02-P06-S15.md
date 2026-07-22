---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S15'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Adapt server doctor to the canonical discovery status without duplicating resolution logic

## Scope

- `src/vaultspec_rag/cli/_service_doctor.py`

## Description

- Derive the live-service axis from the same canonical composition the status verb uses
  when this status directory holds no record.
- Carry the discovery evidence onto the axis so the doctor reports why a holder is not
  serving rather than only that it is not ready.

## Outcome

Doctor and status now agree about a live holder by construction rather than by keeping two
derivations in step, and a holder that has not published a trustworthy address is reported
as present-but-not-live rather than never started.

## Notes

The axis reuses the status adapter's liveness probe rather than repeating it. Duplicating
that probe is precisely how the two surfaces drifted apart before, and the resolution
logic itself stays in the service domain where both adapters read it.

The existing record-present path is untouched, so the established dead-daemon weighting
and its exit code keep their behaviour.
