---
tags:
  - '#exec'
  - '#service-doctor-liveness'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S02'
related:
  - "[[2026-06-24-service-doctor-liveness-plan]]"
---

# Report ready:false or an explicit degraded/needs-restart status when the daemon is dead, keeping the installed-dependency axis present and labelled so the two are never conflated

## Scope

- `src/vaultspec_rag/cli/_service_doctor.py`

## Description

- Made the top-line `ready` honest: when a daemon is expected (discovery file present) but not live and healthy, `ready` is False with a degraded/needs-restart status; with no discovery file, `ready` reflects installed-dependency readiness so a pre-install doctor still works.

## Outcome

A dead daemon is never reported as ready - the #204 false-ready bug is closed without breaking the pre-install check.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (277 passed across process/singleton/lifecycle/CLI; 11 in the doctor/flapping suites). Singleton surfaces (\_machine_lock, \_lifespan) left untouched.
