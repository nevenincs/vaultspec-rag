---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:96bf33247e16b93f97e10b08859353f186164a315cfa6844fe5ad6d727896d7b'
step_id: 'S09'
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
     The S09 and 2026-07-27-maintainability-remediation-plan placeholders are machine-filled by
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
     The Split registry basics, durable recovery, and route-to-recorded-job scenarios and ## Scope

- `src/vaultspec_rag/tests/integration/test_jobs_registry.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Split registry basics, durable recovery, and route-to-recorded-job scenarios

## Scope

- `src/vaultspec_rag/tests/integration/test_jobs_registry.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

Delivered. `test_jobs_registry.py` no longer exists. The three scenario domains the step names are separate modules, with a fourth for quarantine and a shared support module:

| Module | Lines | MI |
| --- | --- | --- |
| `test_jobs_registry_routes.py` | 55 | 57.13 |
| `_jobs_registry_support.py` | 152 | 58.34 |
| `test_jobs_registry_basics.py` | 166 | 45.56 |
| `test_jobs_registry_quarantine.py` | 439 | 43.89 |
| `test_jobs_registry_recovery.py` | 1346 | 2.47 |

All are off the floor. Durable recovery is the outlier at 1346 lines and MI 2.47 - it clears both gates, but it holds the most scenario weight of anything this wave produced.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
