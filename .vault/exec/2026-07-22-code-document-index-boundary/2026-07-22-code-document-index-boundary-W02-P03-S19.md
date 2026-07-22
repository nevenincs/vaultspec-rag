---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S19'
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
     The S19 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Add independent document metadata publication and compatibility markers and ## Scope

- `src/vaultspec_rag/indexer/_document_meta.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add independent document metadata publication and compatibility markers

## Scope

- `src/vaultspec_rag/indexer/_document_meta.py`

## Description

- Define document file and generation metadata with explicit compatibility markers.
- Validate normalized paths, unique point IDs, sorted files, and complete fingerprints.
- Read strictly and publish canonical JSON atomically with a durable flush.

## Outcome

Document generations now have an independent sidecar whose schema, storage
generation, content kind, policy identity, and completeness are explicit.
Malformed or incompatible evidence cannot silently certify a collection.

## Notes

Formatting, lint, and type checks passed. Atomic read/write behavior will be
exercised with the phase's real temporary storage fixture.
