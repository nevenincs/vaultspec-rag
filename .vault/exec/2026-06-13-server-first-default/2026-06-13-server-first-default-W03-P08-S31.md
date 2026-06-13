---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S31'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# add a server doctor readiness CLI verb that renders the shared readiness snapshot in human and JSON modes as a thin adapter

## Scope

- `src/vaultspec_rag/cli/_service_doctor.py`

## Description

- Add a `server doctor` Typer verb in a new module `cli/_service_doctor.py` that calls the service-domain reporter `api.get_readiness()` and renders the bounded per-dependency snapshot in both human (plain `console.print`) and JSON (`_emit_json` envelope) modes.
- Keep it a thin adapter: it performs no provisioning and mutates nothing; the human renderer lists the effective backend, overall readiness, and each dependency's status and detail.

## Outcome

- `vaultspec-rag server doctor` renders the readiness summary; `--json` emits the `{"ok", "command": "server doctor", "data": <snapshot>}` envelope whose `data` is exactly `api.get_readiness()`. `ruff`/`ty`/complexity-gate clean.

## Notes

- Deviation from the plan's named scope `cli/_service_status.py`: the verb lives in a new collision-free module instead, because `_service_status.py` is under concurrent edit by another worker on the shared branch. The service-domain reporter stays the single source; this is only an adapter.
