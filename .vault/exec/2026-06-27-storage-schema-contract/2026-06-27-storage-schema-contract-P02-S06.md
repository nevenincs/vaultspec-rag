---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-07-03'
body_hash: 'sha256:b5160517bb4dda3f1b12b59a4e0ccc44e5343b7f47ca235acb0142819f655147'
step_id: 'S06'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

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
