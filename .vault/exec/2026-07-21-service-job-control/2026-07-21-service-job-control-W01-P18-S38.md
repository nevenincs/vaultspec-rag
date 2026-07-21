---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S38'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-job-control with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S38 and 2026-07-21-service-job-control-plan placeholders are machine-filled by
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
     The Extract canonical enums, immutable resources, outcomes, and serialization into a focused model module while preserving public imports using vaultspec-standard-executor and ## Scope

- `src/vaultspec_rag/job_models.py`
- `src/vaultspec_rag/jobs.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Extract canonical enums, immutable resources, outcomes, and serialization into a focused model module while preserving public imports using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/job_models.py`
- `src/vaultspec_rag/jobs.py`

## Description

- Extract canonical job enums, frozen resources, outcomes, JSON serialization, specification validation, work identity, and capability derivation into `src/vaultspec_rag/job_models.py`.
- Import and re-export the canonical types from `src/vaultspec_rag/jobs.py` as the same class objects while retaining persistence, manager, runtime, logging, and legacy compatibility behavior in place.
- Add an imported-production regression in `src/vaultspec_rag/tests/test_jobs_unit.py` that verifies identity for every canonical model export.

## Outcome

`W01.P18.S38` is complete. The canonical service job model now has one dependency-light source, and every established import through `vaultspec_rag.jobs` remains identity-compatible. The focused job-control and job-manager suite, including all real-filesystem managed persistence integrations, passed 73 tests.

## Notes

- Semantic discovery timed out, so execution used the documented `rg` and direct-read fallback.
- Ruff format and check, ty, strict BasedPyright, diff hygiene, the focused identity regression, and the mandatory safety and intent review all passed.
- Plan and feature validation passed after assigning the inserted modularization phase its unique `W01.P18` display path; the plan checker retains only the intentional non-monotonic Step-order warning for inserted S38-S40 work.
- The test run reported only existing third-party deprecation warnings; no tests were skipped and no persistence or manager extraction was started.
