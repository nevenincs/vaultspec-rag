---
tags:
  - '#exec'
  - '#service-orphan-reaping'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S07'
related:
  - "[[2026-07-23-service-orphan-reaping-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-orphan-reaping with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S07 and 2026-07-23-service-orphan-reaping-plan placeholders are machine-filled by
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
     The Wire the opt-in server stop --orphans flag with its structured reaped-count success and refusal-fault envelope and ## Scope

- `src/vaultspec_rag/cli/_service_stop.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Wire the opt-in server stop --orphans flag with its structured reaped-count success and refusal-fault envelope

## Scope

- `src/vaultspec_rag/cli/_service_stop.py`

## Description

- Add `_expected_singleton_port` resolving the reap scope: explicit `--port`,
  else the discovery-pointer port, else the configured default.
- Add the opt-in `--orphans` flag to `server stop` and a body branch that
  reaps via `_reap_orphan_daemons` and returns before the normal stop logic.
- Emit the broker-facing structured envelope: a `reaped` count on success and an
  `orphan_reap_incomplete` non-zero fault when a matched daemon will not die.

## Outcome

`server stop --orphans` is an explicit, bounded recovery that clears accumulated
orphans while sparing the live singleton, isolated-config, and foreign daemons,
emitting exactly one structured outcome per exit. ruff, ty, basedpyright clean.
Landed with S06 in commit `eb669da3`.

## Notes

Opt-in, never a default, per the operator-views-are-bounded rule - a default
reap would reintroduce the cross-config-kill hazard. The guard tests proving the
predicate and the pair reap (S08/S09) run in the GPU-free daemon-spawning
window.
