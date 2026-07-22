---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S95'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace code-document-index-boundary with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S95 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Verify the preprocessing kill switch suppresses real extractor execution while preserving ownership and stored points and ## Scope

- `src/vaultspec_rag/tests/integration/test_preprocess_integration.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Verify the preprocessing kill switch suppresses real extractor execution while preserving ownership and stored points

## Scope

- `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`

## Description

- Seed a stored code point through a real configured extractor.
- Disable preprocessing, change the owned binary source, and run scoped reconciliation.
- Verify routing ownership remains explicit while extractor execution is suppressed.
- Verify stored IDs, metadata bytes, and cache contents remain unchanged and stale work is reported.

## Outcome

The real-behavior integration test proves that disabling preprocessing suppresses hook
execution without reclassifying owned content or deleting its published state.

## Notes

The first phase-boundary run exposed the newly required immutable preflight argument in the
test call. After passing the resolved full and scoped preflights, the consolidated boundary
suite passed 4 tests with no failures.
