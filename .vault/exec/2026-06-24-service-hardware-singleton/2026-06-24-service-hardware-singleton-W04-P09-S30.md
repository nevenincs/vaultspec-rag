---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-25'
modified: '2026-06-30'
step_id: 'S30'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

# Add --port to server stop and align stop with the status-dir discovery divergence (research F7) so a non-default-port service is stoppable

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Add a `--port` option to `server stop` so a service on a non-default port is
  stoppable, aligning stop with the status-dir discovery divergence (research
  F7) where the status file is missing or records a divergent port.
- Add `_service_pid_on_port`, which resolves the live serving pid and token from
  the service's own `/health` (service domain owns identity) rather than the
  status file.
- Add `_stop_service_on_port`, which targets the running instance on the named
  port, confirms its identity, terminates it, and removes the discovery file only
  when it actually points at that port.
- Extract the terminate-wait-and-log block into `_terminate_and_confirm` and
  reuse it from both the status-file path and the port path.
- Add unit tests for the resolution and no-service-on-port paths plus a CLI test
  proving `stop --port` no longer errors, and an end-to-end lifecycle test that
  stops a real daemon by port with no status file present.

## Outcome

`server stop --port <port>` now stops the running instance on that port via its
`/health` identity even when no status file exists, closing the F7 gap where a
non-default-port service was unstoppable (the verb previously errored
`No such option '--port'`). The default no-`--port` path is unchanged; the
discovery file is only removed when it points at the stopped port, so one
config's stop never erases another's file.

## Notes

Stop keeps identity resolution in the service domain (the `/health` token and
pid), matching `server status --port`, rather than duplicating a CLI-only
identity heuristic.
