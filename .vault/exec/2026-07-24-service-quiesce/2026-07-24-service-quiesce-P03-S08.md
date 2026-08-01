---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:16141a18c0e4d33f5eb5a6c78cbfa9fc61b5fdf7c2cafa02878ae8d110c620f1'
step_id: 'S08'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Add the server pause and server resume CLI verbs that call the route and emit exactly one structured JSON envelope on every exit path, mirroring the start-success and fail-start helper pattern, with already-paused and already-running returning success exit 0 carrying an already\_\* status

## Scope

- `src/vaultspec_rag/cli/_service_quiesce.py`

## Description

- Registered `pause_service`/`resume_service` in the admin transport route
  table (`_POST_BODY_ROUTES`) mapping to `/pause` and `/resume`.
- Added `_service_quiesce.py` with `server pause` / `server resume` verbs on
  the server app, driving the route through `_try_http_admin` and emitting
  exactly one structured envelope on every exit path.
- Imported the module in the cli package (and exported the verbs) so the
  `@server_app.command` decorators register.

## Outcome

`server --help` lists both verbs. An already-satisfied request is a success
(exit 0, `already_paused`/`already_running`); a request that leaves the state
unachieved - a pause the daemon refused because a shutdown latched the gate
open, or a resume that left it held - exits 1 in both human and JSON modes,
so a supervising broker never reads it as done. The route's re-read `paused`
field is what the CLI checks to enforce that.

## Notes

The service-domain half (the localhost route and its status vocabulary) was
S07; this step is only the transport wiring and the CLI adapter, keeping the
operability owned by the service rather than the CLI.
