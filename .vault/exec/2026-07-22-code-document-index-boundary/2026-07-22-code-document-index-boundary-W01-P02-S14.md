---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S14'
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
     The S14 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Verify full, scoped, API, CLI, and service admission parity against one real temporary repository and ## Scope

- `src/vaultspec_rag/tests/integration/test_content_admission.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Verify full, scoped, API, CLI, and service admission parity against one real temporary repository

## Scope

- `src/vaultspec_rag/tests/integration/test_content_admission.py`

## Description

- Build a real temporary project with conventional, ambiguous, and explicitly routed files.
- Compare full and scoped discovery with API, CLI, and resident-service projections.
- Assert stable ownership, disposition reasons, counts, samples, paths, and policy identity.

## Outcome

Every public code-discovery surface consumes the same production admission decision over the
same real project fixture.

## Notes

Reconciled from production integration coverage. Verification is consolidated at the phase
boundary after the remaining production step.
