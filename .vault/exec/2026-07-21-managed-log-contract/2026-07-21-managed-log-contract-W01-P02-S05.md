---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S05'
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
     The S05 and 2026-07-21-managed-log-contract-plan placeholders are machine-filled by
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
     The Exercise real Qdrant-output rollover, retention, restart append, and diagnostic continuity and ## Scope

- `src/vaultspec_rag/tests/test_qdrant_supervise_diagnostics.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Exercise real Qdrant-output rollover, retention, restart append, and diagnostic continuity

## Scope

- `src/vaultspec_rag/tests/test_qdrant_supervise_diagnostics.py`

## Description

- Exercise rollover, sparse retention, zero-backup mode, append after restart, and persistence failure with real files.
- Exercise inherited-pipe timeout and later safe respawn with real subprocesses.
- Assert the diagnostic ring remains bounded and available.

## Outcome

Ten Qdrant supervisor diagnostic tests pass, including the one-writer regression.

## Notes

No mocks, stubs, patches, skips, or xfails were introduced.
