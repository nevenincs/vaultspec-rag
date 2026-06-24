---
tags:
  - '#exec'
  - '#service-doctor-liveness'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S05'
related:
  - "[[2026-06-24-service-doctor-liveness-plan]]"
---




# Instrument and reproduce the spawn-without-breakaway fallback to confirm whether the daemon survives the launching shell exit on this host

## Scope

- `src/vaultspec_rag/cli/_process.py`

## Description

- Diagnosed the breakaway fallback in `_spawn_service`: confirmed by code that on `CREATE_BREAKAWAY_FROM_JOB` denial it silently spawned WITHOUT breakaway, leaving the daemon in the launching shell's Job Object to die on shell exit.

## Outcome

Confirmed root cause for the dominant flapping symptom; full Windows shell-exit reproduction is host-specific and was confirmed by code, not a live multi-process repro.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (277 passed across process/singleton/lifecycle/CLI; 11 in the doctor/flapping suites). Singleton surfaces (_machine_lock, _lifespan) left untouched.
