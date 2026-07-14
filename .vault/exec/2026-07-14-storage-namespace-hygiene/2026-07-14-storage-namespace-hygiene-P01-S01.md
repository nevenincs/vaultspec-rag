---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S01'
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
     The S01 and 2026-07-14-storage-namespace-hygiene-plan placeholders are machine-filled by
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
     The Add the survey snapshot slot: classified survey list plus computed_at, atomic reference swap, thread-safe accessor and ## Scope

- `src/vaultspec_rag/server/_state.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the survey snapshot slot: classified survey list plus computed_at, atomic reference swap, thread-safe accessor

## Scope

- `src/vaultspec_rag/server/_state.py`

## Description

- Add frozen `SurveySnapshot` (surveys tuple + `computed_at`) to `src/vaultspec_rag/server/_state.py`
- Add `publish_survey_snapshot` (tuple copy + single atomic reference assignment) and `survey_snapshot` accessor
- Export the three names through `__all__` and the `vaultspec_rag.server` package namespace

## Outcome

The daemon has one immutable snapshot slot with a lock-free atomic swap; readers can never observe a partially built survey. Commit 7ae79ca.

## Notes

`NamespaceSurvey` is imported under TYPE_CHECKING only, keeping `_state` dependency-light.
