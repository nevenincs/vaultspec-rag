---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
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
