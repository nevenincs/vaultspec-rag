---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S05'
related:
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-autoprune-safety with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S05 and 2026-07-14-storage-autoprune-safety-plan placeholders are machine-filled by
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
     The Add the maintenance cycle function (survey, grace bookkeeping, capped two-tier reclamation, archive retention, one-line health rollup with disk-free warning) and the crash-proof _maintenance_loop task mirroring _heartbeat_loop and ## Scope

- `src/vaultspec_rag/server/_lifecycle.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the maintenance cycle function (survey, grace bookkeeping, capped two-tier reclamation, archive retention, one-line health rollup with disk-free warning) and the crash-proof _maintenance_loop task mirroring _heartbeat_loop

## Scope

- `src/vaultspec_rag/server/_lifecycle.py`

## Description

- Add `_storage_maintenance_tick_sync`: server-mode/knob gated, builds the
  `ReclaimPolicy` from config, opens a short-lived client to the managed
  server, runs `run_maintenance_cycle`, and emits one structured
  `service.maintenance cycle` rollup line (removed/failed/pending/dangling
  bytes/archive counts/namespace statuses) plus a `disk_low` warning under
  a 10GB free-space threshold.
- Add `_maintenance_loop`: same crash-proof shape as `_heartbeat_loop`,
  first run delayed one full interval, interval re-read from config each
  tick (floored at 1s so tests can run short cadences), no exception may
  escape.
- Export both through the server package alias so lifespan wiring and
  tests reach them like the heartbeat helpers.

## Outcome

The cycle is pure storage IO behind the stacked gates; 119 server unit
tests pass; ruff, ruff format, and basedpyright clean.

## Notes

Jobs-registry registration and the /metrics gauges land in S07 per the
plan split; this step's observability is the log rollup.
