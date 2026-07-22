---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S82'
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
     The S82 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Verify code-only jobs launch no document extractor and code cleanup preserves document collection, metadata, and cache and ## Scope

- `src/vaultspec_rag/tests/integration/test_document_lifecycle.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Verify code-only jobs launch no document extractor and code cleanup preserves document collection, metadata, and cache

## Scope

- `src/vaultspec_rag/tests/integration/test_document_lifecycle.py`

## Description

- Index a real source file beside an explicitly document-owned extractor input.
- Assert the code path never launches the document extractor.
- Clean only code state and verify document collection, metadata, and cache bytes.

## Outcome

Code indexing and code cleanup remain document-lifecycle inert. The document
point, published metadata sidecar, and extraction cache survive byte-for-byte,
and the document extractor is never launched.

## Notes

Scoped Ruff and Ty checks passed. The real CUDA and local-Qdrant lifecycle test
passed in 16.09 seconds and released its model and store resources.
