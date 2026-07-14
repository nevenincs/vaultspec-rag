---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S04'
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
     The S04 and 2026-07-14-storage-autoprune-safety-plan placeholders are machine-filled by
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
     The Cover the grace bookkeeping and eligibility gates with unit tests: stamping, restart persistence, reappearance reset, empty-vs-data tiering, cap enforcement, and archive retention and ## Scope

- `src/vaultspec_rag/tests/test_storage_ops.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Cover the grace bookkeeping and eligibility gates with unit tests: stamping, restart persistence, reappearance reset, empty-vs-data tiering, cap enforcement, and archive retention

## Scope

- `src/vaultspec_rag/tests/test_storage_ops.py`

## Description

- Add `test_storage_ops.py` (15 tests) covering the grace clock through the
  real manifest under an isolated status dir: stamping, restart
  persistence, live/unverifiable reset, unknown-prefix no-op.
- Cover `evaluate_reclaim`: unstamped and young orphans pend, aged empty
  orphans become eligible, the data tier needs its longer window,
  non-orphaned statuses never appear, the cycle cap defers with the
  riskless empty tier filling first, and a garbage stamp restarts the
  window rather than qualifying.
- Cover `sweep_archive` on real temp files: missing-dir no-op, age-based
  retention, oldest-first byte-cap eviction.

## Outcome

15/15 passing; ruff and basedpyright clean. The client-coupled paths
(`archive_prefix`, `run_maintenance_cycle`) are deferred to the live
integration tier per the plan.

## Notes

None.
