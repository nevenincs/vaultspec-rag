---
tags:
  - '#exec'
  - '#service-doctor-liveness'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S01'
related:
  - "[[2026-06-24-service-doctor-liveness-plan]]"
---

# Add a live-service axis to server doctor that reads the discovery file and probes health and port, reusing the status-path liveness truth

## Scope

- `src/vaultspec_rag/cli/_service_doctor.py`

## Description

- Added a live-service axis to `server doctor`: it reads the discovery file and computes liveness by reusing `_evaluate_service_signals`/`_compute_state` from the lifecycle module (no duplication of the status-path logic).

## Outcome

doctor now renders two clearly-labelled axes - installed dependencies and live service - in both JSON and plain output.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (277 passed across process/singleton/lifecycle/CLI; 11 in the doctor/flapping suites). Singleton surfaces (\_machine_lock, \_lifespan) left untouched.
