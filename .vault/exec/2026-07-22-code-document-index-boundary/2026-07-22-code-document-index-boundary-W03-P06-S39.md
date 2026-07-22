---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S39'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Keep skip, fail, and passthrough outcomes in their declared kind and require same-kind raw admission for passthrough

## Scope

- `src/vaultspec_rag/indexer/_chunk_worker.py`
- `src/vaultspec_rag/indexer/_preprocess_runner.py`

## Description

- Preserve the declared content kind across skip, fail, and passthrough outcomes.
- Permit raw fallback only when the same kind can decode and admit the source.

## Outcome

Document failures remain document-owned and cannot fall through into code indexing.

## Notes

The binary passthrough test fails closed after the same-kind decoder rejects the input.
