---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S03'
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
     The S03 and 2026-07-14-storage-namespace-hygiene-plan placeholders are machine-filled by
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
     The Wire the warmer task into lifespan startup and shutdown alongside the maintenance task and ## Scope

- `src/vaultspec_rag/server/_lifespan.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Wire the warmer task into lifespan startup and shutdown alongside the maintenance task

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Create the `_survey_warmup_task` in `_start_components` (`src/vaultspec_rag/server/_lifespan.py`), gated on `effective_server_mode` only - deliberately NOT on the autoprune knob, since the survey route serves from the snapshot regardless of scheduled reclamation
- Append it to the periodic-task list so `_shutdown_components` cancels it uniformly

## Outcome

The warmer runs once per daemon lifetime and is torn down through the existing cancel-and-await path. Commit 7ae79ca.

## Notes

Cancelling an already-completed one-shot task is a no-op, so no special-casing was needed.
