---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:3b7abf56da093960387e1a3204e64a69fbd954e021742e30cc3d9d249f3f341b'
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
