---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:786d5bf8193c5228dfb8d0473ce63789f4f1009b22d7fee098b562771348d985'
step_id: 'S26'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Implement full document indexing behind one service-domain entry point

## Scope

- `src/vaultspec_rag/indexer/_document_indexer.py`
- `src/vaultspec_rag/api.py`

## Description

- Add full document discovery, chunking, embedding, reconciliation, and metadata publication.
- Expose the document operation through the service-domain API.

## Outcome

Full document indexing is independently callable and mutates only document state.

## Notes

No unresolved work.
