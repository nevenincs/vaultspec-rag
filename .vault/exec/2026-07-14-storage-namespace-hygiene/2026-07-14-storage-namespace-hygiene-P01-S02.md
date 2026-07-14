---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S02'
related:
  - "[[2026-07-14-storage-namespace-hygiene-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-namespace-hygiene with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S02 and 2026-07-14-storage-namespace-hygiene-plan placeholders are machine-filled by
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
     The Publish the maintenance cycle's survey into the snapshot slot and add the one-shot startup warmer (survey-only, read-only) and ## Scope

- `src/vaultspec_rag/server/_lifecycle.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Publish the maintenance cycle's survey into the snapshot slot and add the one-shot startup warmer (survey-only, read-only)

## Scope

- `src/vaultspec_rag/server/_lifecycle.py`

## Description

- Extend `MaintenanceResult` with a `surveys` field so `run_maintenance_cycle` hands back the classified survey it already computed (`src/vaultspec_rag/storage_ops.py`)
- Publish it from `_storage_maintenance_tick_sync` via the extracted `_publish_survey_from_cycle`, dropping prefixes the cycle just reclaimed
- Add `_storage_survey_warm_sync` (read-only gather + publish, server-mode gated) and the crash-proof one-shot `_survey_warmup_task` with a 5s delay that only fills a cold slot

## Outcome

The hourly footprint walk is no longer thrown away, and the snapshot is warm minutes after startup instead of one full interval later. Commit 7ae79ca.

## Notes

The publish block was extracted into `_publish_survey_from_cycle` because inlining it pushed the tick to cyclomatic rank D (gate max C). The warmer never advances grace stamps and never reclaims - lifecycle-inertness intact.
