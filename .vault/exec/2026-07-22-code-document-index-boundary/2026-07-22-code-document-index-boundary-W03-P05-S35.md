---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:ebed72f9a778e2cc89aac5fc82167555bbe4518b0b3cfec48449885236339606'
step_id: 'S35'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Partition extraction cache lifecycle from code and document collection cleanup

## Scope

- `src/vaultspec_rag/indexer/_preprocess_cache.py`
- `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `src/vaultspec_rag/indexer/_document_indexer.py`

## Description

- Decouple extraction cache lifetime from code and document collection cleanup.

## Outcome

Index cleanup no longer evicts valid extraction results from the independently managed cache.

## Notes

Extractor version and execution identity are the normal invalidation mechanism.
