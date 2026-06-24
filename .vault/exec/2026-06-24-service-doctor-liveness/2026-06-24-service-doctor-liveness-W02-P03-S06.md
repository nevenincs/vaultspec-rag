---
tags:
  - '#exec'
  - '#service-doctor-liveness'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S06'
related:
  - "[[2026-06-24-service-doctor-liveness-plan]]"
---

# Instrument and reproduce the identity-miss discovery-file unlink to confirm whether a concurrent status or start can delete a live daemon's discovery file

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Diagnosed the discovery-file unlink sites in the lifecycle module: confirmed that an ambiguous identity/health miss on a live pid could delete a running daemon's discovery file.

## Outcome

Confirmed the second flapping vector; gates the S08 remediation.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (277 passed across process/singleton/lifecycle/CLI; 11 in the doctor/flapping suites). Singleton surfaces (\_machine_lock, \_lifespan) left untouched.
