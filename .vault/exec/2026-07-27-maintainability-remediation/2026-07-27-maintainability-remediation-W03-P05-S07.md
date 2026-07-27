---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-07-27'
step_id: 'S07'
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
     The S07 and 2026-07-27-maintainability-remediation-plan placeholders are machine-filled by
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
     The Split independent index job-control scenarios and retain real service assertions and ## Scope

- `src/vaultspec_rag/tests/integration/test_index_job_control.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Split independent index job-control scenarios and retain real service assertions

## Scope

- `src/vaultspec_rag/tests/integration/test_index_job_control.py`

## Description

- Replaced the index-job-control monolith with direct stream, managed-control,
  and publication scenario modules plus one shared real-behavior support module.
- Moved fixture registration to the integration package so imported support is
  assertion-rewritten before pytest plugin loading.
- Updated the managed cancellation scenario to park a valid upsert at the real
  pre-mutation collection-lock gate; cancellation proves zero persistence and
  no spurious failure while the separate store-retry test owns failure
  precedence.

## Outcome

- The legacy monolith is removed; all 15 direct scenarios collect without
  warnings and retain production Qdrant, indexing, and service paths.
- Independent review approved the split after fixture-registration and scenario
  wording corrections.
- Focused validation passed: `ruff format --check`, `ruff check`, `ty check`,
  and `py_compile` on the split modules and support; pytest collect-only found
  15 scenarios; the exact cancellation scenario passed; the complete focused
  three-module gate passed 15 tests in 151.85 seconds.

## Notes

- The former dimension-mismatch setup is now rejected by production schema
  admission before the pipeline. Replaced it with an empty correctly shaped
  collection to preserve the intended post-admission, pre-mutation gate proof.
