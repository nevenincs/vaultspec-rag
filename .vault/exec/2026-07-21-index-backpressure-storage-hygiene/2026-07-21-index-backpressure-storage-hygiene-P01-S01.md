---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S01'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# add a configurable server-mode qdrant client timeout and a write-side classification wrapper around upsert_document_chunks and upsert_code_chunks (typed StorageWriteError with error_kind, bounded retry for transient kinds, disk_full non-retryable)

## Scope

- `bounded retry for transient kinds`
- `disk_full non-retryable) around upsert_document_chunks and upsert_code_chunks`
- `src/vaultspec_rag/store.py`

## Description

## Outcome

## Notes
