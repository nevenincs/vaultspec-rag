---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S93'
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
     The S93 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Verify watcher classification matches full and scoped discovery for ordinary real file events and ## Scope

- `src/vaultspec_rag/tests/integration/test_watcher_content_admission.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Verify watcher classification matches full and scoped discovery for ordinary real file events

## Scope

- `src/vaultspec_rag/tests/integration/test_watcher_content_admission.py`

## Description

- Emit ordinary real filesystem additions and modifications through the watcher filter.
- Compare watcher decisions with full and scoped production discovery.
- Cover conventional, ambiguous, explicitly routed, and ignored paths.

## Outcome

Ordinary watcher events agree with full and scoped discovery for the same active policy
snapshot and disposition vocabulary.

## Notes

Reconciled from production integration coverage in commit `3602ee9`.
