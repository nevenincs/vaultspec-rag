---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S36'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Exercise the end-to-end HTTP, transport, and CLI outcome matrix for exact IDs, stale revisions, already-satisfied requests, conflicts, and force rejection using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/tests/integration/test_service_job_control_e2e.py`

## Description

- Serve production job-control routes over a real loopback Uvicorn socket.
- Create and inspect one paused job through the typed HTTP transport.
- Verify command-line interface (CLI) exact-ID lookup and prefix rejection.
- Exercise stale revision conflict and stale already-satisfied replay.
- Exercise active-delete conflict, force rejection, graceful stop, and deletion.
- Restore discovery, authentication, configuration, and singleton state on exit.

## Outcome

The real HTTP, transport, and CLI outcome matrix passes. Exact identifiers work
through every layer, JSON mode emits one structured envelope, stale mutations
conflict while idempotent replay succeeds, active deletion is rejected, force
termination is explicitly unavailable, and graceful cancellation permits
terminal deletion. Ruff and BasedPyright pass. Independent review passed with
no open findings.

## Notes

The focused selector passed in 3.71 seconds. Review moved the Uvicorn stopped
assertion after unconditional restoration so even a shutdown timeout cannot
leak the test token, discovery path, environment, cached configuration, or job
singleton.
