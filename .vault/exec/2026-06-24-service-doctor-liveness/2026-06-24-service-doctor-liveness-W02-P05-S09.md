---
tags:
  - '#exec'
  - '#service-doctor-liveness'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S09'
related:
  - "[[2026-06-24-service-doctor-liveness-plan]]"
---




# Add a no-mock test that a daemon survives a simulated parent-shell exit on this platform

## Scope

- `src/vaultspec_rag/tests/integration/test_daemon_survives_shell_exit.py`

## Description

- Added no-mock tests for the breakaway fallback (asserting it fails loud / detaches rather than producing a shell-bound daemon).

## Outcome

The remediation path is guarded; any behaviour requiring the live Windows host is noted as host-only.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (277 passed across process/singleton/lifecycle/CLI; 11 in the doctor/flapping suites). Singleton surfaces (_machine_lock, _lifespan) left untouched.
