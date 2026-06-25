---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-25'
modified: '2026-06-25'
step_id: 'S30'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-hardware-singleton with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S30 and 2026-06-24-service-hardware-singleton-plan placeholders are machine-filled by
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
     The Add --port to server stop and align stop with the status-dir discovery divergence (research F7) so a non-default-port service is stoppable and ## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

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
