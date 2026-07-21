---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S02'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# bound the CUDA-OOM encode recovery in encode_documents and encode_documents_sparse to a halving ladder with floor batch size 1 that raises the underlying error on persistent failure

## Scope

- `src/vaultspec_rag/embeddings.py`

## Description

## Outcome

## Notes
