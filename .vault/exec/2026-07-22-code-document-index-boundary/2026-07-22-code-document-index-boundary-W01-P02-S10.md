---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S10'
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
     The S10 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Route scoped discovery through the shared classifier and resolved policy snapshot and ## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Route scoped discovery through the shared classifier and resolved policy snapshot

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Verify scoped paths normalize to project-relative policy identities.
- Verify scoped admission delegates to the supplied immutable snapshot.
- Verify only admitted code-owned paths enter hashing and publication.

## Outcome

Scoped indexing consumes the same ownership and admission authority as full discovery, with
rejections kept out of the code execution path.

## Notes

Reconciled from production commit `e1254ed`; no additional code change was required.
