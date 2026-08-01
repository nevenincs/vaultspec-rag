---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:b8c32e77d83933fea0948cfe4dc16cae1622aa911b9505c32f9388b9bec11aa9'
step_id: 'S102'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Implement scoped incremental document indexing behind the service-domain entry point

## Scope

- `src/vaultspec_rag/indexer/_document_indexer.py`
- `src/vaultspec_rag/api.py`

## Description

- Normalize and validate caller-selected paths.
- Reconcile only the selected document sources while retaining unrelated metadata.

## Outcome

Scoped document indexing supports watcher-sized change sets without crossing collection boundaries.

## Notes

No unresolved work.
