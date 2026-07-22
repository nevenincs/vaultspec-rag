---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
step_id: 'S04'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Define immutable job specifications, canonical states, capabilities, revisions, attempt lineage, and structured outcomes using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- Define canonical operation, source, mode, observed-state, desired-state, resume-strategy, and outcome vocabularies.
- Add frozen specifications, capabilities, initiator, attempt-lineage, timestamp, progress, runtime, and resource snapshot types.
- Add immutable exact-ID job snapshots and structured command outcomes with JSON-ready serialization.
- Preserve every legacy record, persistence, callback, and background-dispatch function without behavior changes.
- Verify the type layer with Ruff, `ty`, strict BasedPyright, and existing job-registry behavior.

## Outcome

The service domain now has an immutable canonical resource representation for future
manager transitions and adapters. Its serialization exposes the accepted revision,
attempt lineage, desired and observed states, control timestamps, capabilities, runtime,
resources, progress, result, and stable outcome envelope while legacy consumers continue
to receive their existing dictionary records.

## Notes

All jobs unit behavior passed. The integration registry run completed 41 tests overall;
its two live-service cases could not enter the test body because the concurrently changing
shared tree lacked the unrelated `read_service_log` import required by service startup.
No S04 assertion failed. Concurrent branch activity required committing the production
type layer before this traceability record was attached.
