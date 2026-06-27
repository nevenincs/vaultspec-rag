---
tags:
  - '#exec'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S03'
related:
  - "[[2026-06-27-rag-broker-affordances-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace rag-broker-affordances with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S03 and 2026-06-27-rag-broker-affordances-plan placeholders are machine-filled by
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
     The Add the --json option and emit one envelope per outcome (already_running, started, port_in_use, machine_owned, daemon_breakaway, start_timeout) and ## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the --json option and emit one envelope per outcome (already_running, started, port_in_use, machine_owned, daemon_breakaway, start_timeout)

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Added the `--json` option to `server start` and two outcome helpers (`_start_success`, `_fail_start`) that emit one `_emit_json` envelope (JSON mode) or the bespoke human lines (otherwise).
- Routed every exit path through them: `already_running`/`started` (ok, exit 0) and `port_in_use`/`machine_owned`/`daemon_breakaway`/`start_died`/`start_timeout` (ok:false, exit 1).
- Extended `_ensure_qdrant_binary` with `json_mode`, emitting `qdrant_missing`/`qdrant_provision_failed` envelopes; suppressed the Rich spinner in JSON mode (a nullcontext) so stdout carries one clean envelope.

## Outcome

`server start --json` emits exactly one machine-readable outcome on every exit path; a supervising broker can attach on `already_running` (exit 0) instead of reading a gateway fault. The human output is unchanged.

## Notes

Discovered rag's spinner has no `visible` kwarg, so JSON mode swaps the live status for `contextlib.nullcontext()`. The machine_owned envelope carries the holder pid; port_in_use carries the port.
