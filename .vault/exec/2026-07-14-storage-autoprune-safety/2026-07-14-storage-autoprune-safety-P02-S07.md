---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S07'
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
     The S07 and 2026-07-14-storage-autoprune-safety-plan placeholders are machine-filled by
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
     The Register each cycle in the jobs registry with source maintenance and trigger schedule, and export the rollup gauges (disk free, namespace counts by status, dangling bytes, pending-grace counts) through /metrics and server status and ## Scope

- `src/vaultspec_rag/jobs.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Register each cycle in the jobs registry with source maintenance and trigger schedule, and export the rollup gauges (disk free, namespace counts by status, dangling bytes, pending-grace counts) through /metrics and server status

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- Widen the jobs taxonomy: `Source` gains `maintenance`, `Trigger` gains
  `schedule`, so cycles are first-class records in `server jobs` and the
  `/jobs` route.
- Register each cycle with `record_start("maintenance", "schedule",
  command="storage_maintenance")` and finish it with a one-line summary
  (`error` phase when any reclaim failed; exception path finishes the
  record before re-raising into the loop's catch).
- Add the rollup metrics to the inline holder rendered by `/metrics`:
  counters `maintenance_cycles_total` / `maintenance_reclaims_total`,
  gauges disk-free, dangling bytes, pending grace, orphaned namespaces,
  last reclaimed bytes - refreshed inline by the tick, never a collector.

## Outcome

134 server + jobs unit tests pass; ruff, ruff format, and basedpyright
clean.

## Notes

`server status` visibility rides the jobs registry (the cycle appears in
the operational jobs block status already renders) rather than a bespoke
status field; the /metrics gauges carry the numeric rollup.
