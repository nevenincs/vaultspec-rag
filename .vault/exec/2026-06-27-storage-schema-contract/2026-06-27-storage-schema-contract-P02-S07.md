---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-07-03'
step_id: 'S07'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

# Build code chunk payloads from the TypedDict in the code upsert path

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Added the pure builder `_code_chunk_payload` returning `CodeChunkPayload`, covering all 17 code-chunk fields including the document-preprocessing hook locators.
- Routed `upsert_code_chunks` to call the builder.

## Outcome

The code payload is built from the typed contract in one place; covered by the parity test's golden-shape assertion.

## Notes

None.
