---
tags:
  - '#exec'
  - '#control-plane-affordances'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:55cc637f53ba8c25e9330341fedbd6c521e4874e105cee7d8856c389accbed41'
step_id: 'S05'
related:
  - "[[2026-07-13-control-plane-affordances-plan]]"
---

# Add --json to server stop with one envelope per exit path (stopped, already_stopped, cleaned, reclaimed as ok:true and identity_unconfirmed as ok:false) and make the identity-unconfirmed skip exit 1 in both human and json modes, covering the --port variant

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Add `_stop_success` / `_fail_stop` helpers mirroring the start envelope
  machinery, tagged `service.stop`.
- Add `--json` to `server stop`; every exit path converges on one helper:
  `stopped`, `already_stopped` (no discovery file and no reclaimable holder,
  or nothing answering the named `--port`), `cleaned` (stale discovery file
  for a confirmed-dead pid), `reclaimed` (machine-singleton holder
  terminated) as `ok:true`; `identity_unconfirmed` as `ok:false`.
- Make the identity-unconfirmed skip exit 1 in both human and `--json`
  modes - a stop that leaves the service running is a failure, per the
  broker-facing envelope contract. Both the default and `--port` variants.
- Document the exit-code contract in the command docstring and `--json`
  help text.

## Outcome

`server stop --json` emits exactly one envelope per exit path;
`_terminate_and_confirm` writes only to the daemon log, so json mode stays
clean on stdout. Existing stop unit tests (stop-port, singleton reclaim,
CLI stop suite) pass; ruff/basedpyright clean.

## Notes

Deliberate behavior change: the skip path previously exited 0; it now
exits 1 in both modes. Approved in the ADR; changelog must call it out.
