---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:34f658bf99f26fdbaf5d22486d867a27d7a61d62e28c19be3f3c521882f45c91'
step_id: 'S12'
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
     The S12 and 2026-07-27-maintainability-remediation-plan placeholders are machine-filled by
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
     The Split startup, shutdown, discovery, and orphan-reaping lifecycle scenarios and ## Scope

- `src/vaultspec_rag/tests/integration/test_service_lifecycle.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Split startup, shutdown, discovery, and orphan-reaping lifecycle scenarios

## Scope

- `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

Delivered. `test_service_lifecycle.py` no longer exists. The four lifecycle domains the step names are separate modules over a shared helper module:

| Module | Lines | MI |
| --- | --- | --- |
| `test_service_lifecycle_orphan_reap.py` | 286 | 55.44 |
| `test_service_lifecycle_discovery.py` | 436 | 44.14 |
| `_service_lifecycle_helpers.py` | 637 | 26.92 |
| `test_service_lifecycle_runtime.py` | 646 | 23.25 |
| `test_service_lifecycle_startup.py` | 824 | 11.72 |

Startup and shutdown share the runtime and startup modules rather than splitting on the verb, because a shutdown assertion reads against the startup that produced the process it is stopping. All five are off the floor.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
