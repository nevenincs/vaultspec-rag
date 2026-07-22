---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S28'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Verify GET, POST, PUT, and DELETE client operations and structured conflicts against a real server using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/tests/integration/test_service_job_control.py`

## Description

- Start the production Starlette route table through a real Uvicorn loopback
  socket.
- Publish isolated service discovery and authentication state for the client.
- Exercise typed create, exact detail, desired-state, retry, and delete calls.
- Assert real GET, POST, PUT, and DELETE behavior and structured conflicts.
- Restore the process-global job, token, environment, and configuration state
  on every exit path.

## Outcome

The client transport completed one full paused-job lifecycle against the real
HTTP server. It preserved structured success and error envelopes for force
rejection, active deletion conflict, cancellation, linked retry, terminal
deletion, and missing exact detail. The focused test passes; Ruff, Ruff format,
and BasedPyright pass.

Independent re-review passed with no remaining critical, high, or medium
findings.

## Notes

The first verification passed before review. Review identified missing retry
coverage and cleanup assertions outside the guaranteed restoration boundary;
both were corrected and the focused real-server test passed again. One
intermediate collection attempt coincided with an unrelated shared-main edit
to search availability; no shared change was reverted or overwritten.
Final BasedPyright review also replaced the fixture's deprecated iterator
annotation with its explicit generator type.
