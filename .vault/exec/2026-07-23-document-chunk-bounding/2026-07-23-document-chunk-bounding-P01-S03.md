---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S03'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# route hook-emitted unit text through the shared bounded splitter in the units branch

## Scope

- `src/vaultspec_rag/indexer/_chunk_worker.py`

## Description

- Route each hook-emitted unit's text through the shared bounded splitter in `_document_chunks_from_output` (`src/vaultspec_rag/indexer/_chunk_worker.py`), one chunk per fragment.
- Introduce `_document_text_splitter` so the raw-text branch and the units branch split through one configuration carried on `ChunkExecutionPolicy`.
- Thread `ChunkExecutionPolicy` into `_document_chunks_from_text` and `_document_chunks_from_output` from every call site.

## Outcome

No unit reaches the encoder above the split budget on either branch; whitespace-only fragments are dropped exactly as the raw-text branch drops them.

## Notes

An initial verbatim-emission fix landed earlier the same day in commit `29168706` after a direct user order; this step converges it onto the shared derived-budget configuration.
