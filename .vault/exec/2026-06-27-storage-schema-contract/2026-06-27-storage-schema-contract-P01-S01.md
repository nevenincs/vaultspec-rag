---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S01'
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
     The S01 and 2026-06-27-storage-schema-contract-plan placeholders are machine-filled by
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
     The Define STORAGE_SCHEMA_VERSION, the dense/sparse vector-name and distance constants, and the TypedDict payload shapes for vault doc, vault chunk, and code chunk and ## Scope

- `src/vaultspec_rag/store_schema.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Define STORAGE_SCHEMA_VERSION, the dense/sparse vector-name and distance constants, and the TypedDict payload shapes for vault doc, vault chunk, and code chunk

## Scope

- `src/vaultspec_rag/store_schema.py`

## Description

- Created the `store_schema.py` neutral leaf module with its torch-free contract docstring.
- Defined `STORAGE_SCHEMA_VERSION = 1` with the bump policy in a comment (breaking-only; additive fields do not bump).
- Defined the collection-name constants (`VAULT_COLLECTION`, `CODE_COLLECTION`), the vector constants (`DENSE_VECTOR_NAME`, `SPARSE_VECTOR_NAME`, `DENSE_DISTANCE`, `DEFAULT_DENSE_DIM`), and the three ID-scheme constants.
- Defined the `VaultDocPayload`, `VaultChunkPayload` (with `doc_content` as `NotRequired`), and `CodeChunkPayload` TypedDicts mirroring the current upsert payloads field-for-field.

## Outcome

The schema module exists and is the single typed definition of the Qdrant payload shapes; the field sets match the inline upsert dicts in `store.py` exactly (verified against the doc, vault-chunk, and code-chunk literals before authoring).

## Notes

`doc_content` is `NotRequired` because it travels only on the ordinal-0 vault chunk; the conditional add stays in `store.py`.
