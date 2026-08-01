---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:8185110c025b5a5541e0fc0703cb4f15933104ab7588b84a0fb30d8db6d76570'
step_id: 'S25'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Dispatch bounded streaming batches to the collection selected by each admission disposition

## Scope

- `src/vaultspec_rag/indexer/_streaming.py`
- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Add bounded document embedding slices.
- Publish each slice only through document collection operations.

## Outcome

Code and document slices now have separate storage dispatch paths.

## Notes

No unresolved work.
