---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
step_id: 'S09'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Verify real-filesystem persistence, exact task ownership, atomic replacement, paused restoration, and interrupted recovery using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/tests/integration/test_jobs_registry.py`

## Description

- Persist queued work to a real temporary filesystem and verify pause and idempotency restoration under the same exact ID.
- Bind a live attempt to real asyncio tasks and reject release or acknowledgement from a different task identity.
- Restore a persisted live attempt as immutable interrupted history with no runtime owner.
- Read the state file concurrently with repeated lifecycle writes and verify every observable generation is complete JSON.
- Reject malformed state without partially populating the manager.
- Retry Windows atomic replacement for a bounded interval when a concurrent reader transiently holds the destination.

## Outcome

The durable manager contract is verified end to end against the filesystem and real task
objects. Atomic generations remain parseable, stale task identities cannot release current
ownership, paused jobs retain identity, and crashed live work becomes interrupted history.

## Notes

The concurrent reader exposed Windows `Access denied` behavior during `os.replace`; the
production writer now retries only the rename within a short bounded window and still rolls
back if contention persists. All 11 non-GPU registry integration tests passed, along with
Ruff, formatting, `ty`, and strict BasedPyright. The two existing live-service GPU cases were
excluded because this worktree has no provisioned Qdrant server binary.
