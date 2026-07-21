---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S17'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace managed-log-contract with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S17 and 2026-07-21-managed-log-contract-plan placeholders are machine-filled by
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
     The Run focused unit and integration suites for configuration, writers, routes, transport, and CLI and ## Scope

- `src/vaultspec_rag/tests` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Run focused unit and integration suites for configuration, writers, routes, transport, and CLI

## Scope

- `src/vaultspec_rag/tests`

## Description

- Run focused configuration, reader, writer, route, transport, and CLI tests.
- Run real service rollover checks against isolated daemon processes.
- Rerun the consolidated matrix after the supervisor lifecycle revision.

## Outcome

The final focused matrix passes 125 tests; both real service rollover scenarios also pass.

## Notes

One cold model-cache run exceeded its 90-second service startup allowance; the cache-warm rerun completed successfully and the logging assertion passed.
