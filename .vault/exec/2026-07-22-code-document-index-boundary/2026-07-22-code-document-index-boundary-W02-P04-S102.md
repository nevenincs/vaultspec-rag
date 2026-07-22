---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
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
