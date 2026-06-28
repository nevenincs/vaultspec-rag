---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S03'
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
     The S03 and 2026-06-27-storage-schema-contract-plan placeholders are machine-filled by
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
     The Implement describe_storage_schema building the effective config-derived wire descriptor without importing torch and ## Scope

- `src/vaultspec_rag/store_schema.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement describe_storage_schema building the effective config-derived wire descriptor without importing torch

## Scope

- `src/vaultspec_rag/store_schema.py`

## Description

- Implemented `describe_storage_schema()` returning the bounded wire descriptor: `{version, vault:{collection, vectors, payload_fields, indexes, id_scheme}, code:{...}, models}`.
- Read the EFFECTIVE dense dimension and model identity from config via lazy helpers (`_effective_dense_dim`, `_effective_models`), so an `embedding_dimension`/model override is reflected rather than the code constant.
- Derived the payload-field lists from the TypedDict `__annotations__` so the descriptor and the drift test share one source.

## Outcome

The descriptor advertises both the static shape version and the live effective values, and is JSON-serialisable. Loads no model and touches no GPU (config read only), so it is safe on the `/readiness` path.

## Notes

The dense vector descriptor is shared by both collections; `assert_compatible` reads it from the vault block as the canonical location.
