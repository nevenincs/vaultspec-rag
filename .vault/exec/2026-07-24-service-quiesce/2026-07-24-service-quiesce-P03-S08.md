---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S08'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-quiesce with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S08 and 2026-07-24-service-quiesce-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Add the server pause and server resume CLI verbs that call the route and emit exactly one structured JSON envelope on every exit path, mirroring the start-success and fail-start helper pattern, with already-paused and already-running returning success exit 0 carrying an already_* status and ## Scope

- `src/vaultspec_rag/cli/_service_quiesce.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the server pause and server resume CLI verbs that call the route and emit exactly one structured JSON envelope on every exit path, mirroring the start-success and fail-start helper pattern, with already-paused and already-running returning success exit 0 carrying an already_* status

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
