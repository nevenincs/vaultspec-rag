---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S03'
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
     The S03 and 2026-07-21-service-job-control-plan placeholders are machine-filled by
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
     The Verify control primitives and configuration through imported production behavior using vaultspec-standard-executor and ## Scope

- `src/vaultspec_rag/tests/test_job_control_unit.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Verify control primitives and configuration through imported production behavior using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/tests/test_job_control_unit.py`

## Description

- Exercise cross-thread pause delivery through nested protected spans and their outer safe edge.
- Verify reversible pause, absorbing repeated cancellation, and protected-entry delivery.
- Preserve application failures while leaving cooperative control pending for the next checkpoint.
- Verify the runtime protocol and no-control implementation through imported production objects.
- Resolve defaults, environment overrides, and invalid settings in isolated Python processes.

## Outcome

Fifteen imported-production tests now prove the S01 and S02 contracts without test doubles or
runtime mutation. The focused suite passes, as do Ruff formatting and lint, ty, and strict
BasedPyright checks.

## Notes

Environment-sensitive cases execute in fresh child interpreters with only the two job-control
variables isolated. Job-manager behavior remains assigned to later plan Steps. The test run
reported only pre-existing `pytest-durations` deprecation warnings.
