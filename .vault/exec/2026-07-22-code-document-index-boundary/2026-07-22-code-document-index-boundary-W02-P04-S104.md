---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S104'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Ingest explicitly routed decodable raw documents without launching an extractor

## Scope

- `src/vaultspec_rag/indexer/_document_indexer.py`
- `src/vaultspec_rag/indexer/_chunk_worker.py`

## Description

- Decode explicitly routed raw documents through the resolved decoder.
- Build document-native chunks without launching an extractor.

## Outcome

Decodable raw documents can be document-owned without repository-layout assumptions.

## Notes

No unresolved work.
