---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-07-03'
step_id: 'S01'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

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
