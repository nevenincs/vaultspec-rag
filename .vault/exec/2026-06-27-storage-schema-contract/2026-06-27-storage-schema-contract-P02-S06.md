---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S06'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-schema-contract with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S06 and 2026-06-27-storage-schema-contract-plan placeholders are machine-filled by
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
     The Build vault document and vault chunk payloads from the TypedDicts in the upsert paths and ## Scope

- `src/vaultspec_rag/store.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Build vault document and vault chunk payloads from the TypedDicts in the upsert paths

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Added the module-level pure builders `_vault_doc_payload` and `_vault_chunk_payload`, each returning the corresponding TypedDict, as the one place each vault payload shape is constructed.
- Routed `upsert_documents` and `upsert_document_chunks` to call the builders, keeping the ordinal-0 `doc_content` behavior inside `_vault_chunk_payload`.
- Imported `store_schema` at module scope in `store.py` (a torch-free leaf, no import cycle).

## Outcome

The vault payloads are built from the typed contract; the builders are unit-testable without Qdrant. basedpyright is clean and the 1136-test unit suite passes unchanged.

## Notes

Extracted the payloads into helper functions (rather than inline typed dicts) so the parity test can assert them directly in the CI unit gate without a live store.
