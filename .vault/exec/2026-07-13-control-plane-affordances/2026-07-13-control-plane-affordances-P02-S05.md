---
tags:
  - '#exec'
  - '#control-plane-affordances'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S05'
related:
  - "[[2026-07-13-control-plane-affordances-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace control-plane-affordances with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S05 and 2026-07-13-control-plane-affordances-plan placeholders are machine-filled by
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
     The Add --json to server stop with one envelope per exit path (stopped, already_stopped, cleaned, reclaimed as ok:true and identity_unconfirmed as ok:false) and make the identity-unconfirmed skip exit 1 in both human and json modes, covering the --port variant and ## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

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
