---
tags:
  - '#exec'
  - '#service-doctor-liveness'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S03'
related:
  - "[[2026-06-24-service-doctor-liveness-plan]]"
---

# Reflect the real live qdrant runtime state in the doctor output rather than the binary-on-disk default that reads ready when no supervisor exists in-process

## Scope

- `src/vaultspec_rag/cli/_service_doctor.py`

## Description

- The doctor qdrant/live state now derives from the live probe rather than the binary-on-disk default that read READY whenever no supervisor existed in-process.

## Outcome

doctor reflects real runtime state when a daemon is running.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (277 passed across process/singleton/lifecycle/CLI; 11 in the doctor/flapping suites). Singleton surfaces (\_machine_lock, \_lifespan) left untouched.
