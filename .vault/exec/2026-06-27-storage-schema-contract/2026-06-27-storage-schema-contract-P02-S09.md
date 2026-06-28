---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S09'
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
     The S09 and 2026-06-27-storage-schema-contract-plan placeholders are machine-filled by
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
     The Source the dense vector params (name, default dimension, distance) from the schema module in collection create and ## Scope

- `src/vaultspec_rag/store.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Source the dense vector params (name, default dimension, distance) from the schema module in collection create

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Sourced `EMBEDDING_DIM` from `store_schema.DEFAULT_DENSE_DIM` so the dense-dimension default has one definition.
- Replaced the literal `"dense"` / `"sparse"` vector names and `models.Distance.COSINE` in `_ensure_collection` with `store_schema.DENSE_VECTOR_NAME`, `SPARSE_VECTOR_NAME`, and `models.Distance(store_schema.DENSE_DISTANCE)`.

## Outcome

Collection creation reads the vector layout from the schema module; a rename or distance change is now a one-line change in the contract that the drift test verifies against a live collection.

## Notes

Used the by-value enum lookup `models.Distance(store_schema.DENSE_DISTANCE)` so the constant carries the qdrant value string ("Cosine") directly.
