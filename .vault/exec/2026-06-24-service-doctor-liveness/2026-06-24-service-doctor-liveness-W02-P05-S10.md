---
tags:
  - '#exec'
  - '#service-doctor-liveness'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S10'
related:
  - "[[2026-06-24-service-doctor-liveness-plan]]"
---

# Add a no-mock test that a concurrent lifecycle command does not unlink a live daemon's discovery file on a transient identity miss

## Scope

- `src/vaultspec_rag/tests/integration/test_daemon_survives_shell_exit.py`

## Description

- Added no-mock tests for the unlink guard: a confirmed-dead pid unlinks the file; a live-but-ambiguous pid keeps it.

## Outcome

The unlink-decision contract is proven with real objects, no mocks.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (277 passed across process/singleton/lifecycle/CLI; 11 in the doctor/flapping suites). Singleton surfaces (\_machine_lock, \_lifespan) left untouched.
