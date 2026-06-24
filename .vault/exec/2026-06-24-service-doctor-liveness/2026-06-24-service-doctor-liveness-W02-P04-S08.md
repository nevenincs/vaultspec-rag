---
tags:
  - '#exec'
  - '#service-doctor-liveness'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S08'
related:
  - "[[2026-06-24-service-doctor-liveness-plan]]"
---

# Unlink the discovery file only when the holder is confirmed dead, never on an ambiguous identity result, so a transient health or PID miss cannot delete a live service's file

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Remediated the unlink: added a pure `_should_unlink_discovery_file(pid_alive)` guard (`return not pid_alive`) applied at every unlink site, so the discovery file is removed only when the holder is confirmed dead and kept on an ambiguous/live miss.

## Outcome

A transient identity/health miss can no longer delete a live daemon's discovery file.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (277 passed across process/singleton/lifecycle/CLI; 11 in the doctor/flapping suites). Singleton surfaces (\_machine_lock, \_lifespan) left untouched.
