---
tags:
  - '#exec'
  - '#service-doctor-liveness'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S04'
related:
  - "[[2026-06-24-service-doctor-liveness-plan]]"
---

# Add a no-mock test asserting doctor reports a not-ready or degraded live status with no daemon running while still reporting dependency readiness truthfully

## Scope

- `src/vaultspec_rag/tests/integration/test_service_doctor_liveness.py`

## Description

- Added a no-mock test asserting doctor reports a not-ready/degraded live status when the discovery file points at a dead pid / closed port, while still reporting installed-dependency readiness; and the no-discovery-file case still reports dependency readiness.

## Outcome

The live axis is proven against real (dead) signals with no mocks.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (277 passed across process/singleton/lifecycle/CLI; 11 in the doctor/flapping suites). Singleton surfaces (\_machine_lock, \_lifespan) left untouched.
