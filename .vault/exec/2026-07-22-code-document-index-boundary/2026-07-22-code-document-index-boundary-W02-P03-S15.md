---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S15'
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
     The S15 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Define document chunk, locator, metadata, payload, and result models distinct from source chunks and ## Scope

- `src/vaultspec_rag/_store_models.py`
- `src/vaultspec_rag/search/_models.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Define document chunk, locator, metadata, payload, and result models distinct from source chunks

## Scope

- `src/vaultspec_rag/_store_models.py`
- `src/vaultspec_rag/search/_models.py`

## Description

- Define a document-native locator and canonical immutable metadata value.
- Define document payload and chunk types independently from `CodeChunk` and vault models.
- Define a document-specific search result without widening the legacy result contract.

## Outcome

Document content now has an explicit model boundary that preserves native
locators, document and unit metadata, extractor identity, and vector fields.
Canonical metadata and the complete chunk graph survive pickling deterministically.

## Notes

Formatting, lint, type checking, canonical-metadata materialization, and pickle
round-trip probes passed. No storage mutation was introduced in this step.
