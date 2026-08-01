---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:8f07ec479b1dc698255f30e333a3bf8f49f354d39ef1b236cc2f48fcb6d1c402'
step_id: 'S101'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Implement unscoped incremental document indexing behind the service-domain entry point

## Scope

- `src/vaultspec_rag/indexer/_document_indexer.py`
- `src/vaultspec_rag/api.py`

## Description

- Compare document source hashes against independently published metadata.
- Reconcile discovered additions, modifications, and removals.

## Outcome

Unscoped incremental document indexing converges without rebuilding unchanged documents.

## Notes

No unresolved work.
