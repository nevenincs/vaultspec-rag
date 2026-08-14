---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:91b34edb8fcc4a3e7d46083fe7c16b632b2d2f06a114c0b980d97270a9cd3239'
step_id: 'S05'
related:
  - "[[2026-07-27-maintainability-remediation-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace maintainability-remediation with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S05 and 2026-07-27-maintainability-remediation-plan placeholders are machine-filled by
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
     The Split presentation, query, watch, and control adapters into direct CLI owners and ## Scope

- `src/vaultspec_rag/cli/_service_jobs.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Split presentation, query, watch, and control adapters into direct CLI owners

## Scope

- `src/vaultspec_rag/cli/_service_jobs.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

Delivered. `cli/_service_jobs.py` no longer exists; the four responsibilities the step names have concrete owners, plus a collection owner:

| Module | Lines | MI |
| --- | --- | --- |
| `_service_jobs_watch.py` | 67 | 79.94 |
| `_service_jobs_collection.py` | 250 | 47.42 |
| `_service_jobs_query.py` | 307 | 43.77 |
| `_service_jobs_control.py` | 418 | 34.25 |
| `_service_jobs_presentation.py` | 1123 | 3.41 |

Every owner is off the maintainability floor. Presentation is the weakest at 3.41 and the largest at 1123 lines; it is under the module ceiling and off the floor, so it satisfies this step, but it is the one owner that would repay a further division by rendered surface.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
