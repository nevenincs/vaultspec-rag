---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-06-12'
step_id: 'S04'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Add doc_id payload plumbing, delete-by-document filtering, and index schema version detection that triggers a one-time vault collection rebuild

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Add `VaultChunk` and `upsert_document_chunks` (point key doc_id#c{ordinal},
  full body only on the head chunk) to `store.py`.
- Switch `delete_documents` to a doc_id filter delete; rework `get_by_id` to
  the head chunk with a pre-chunking fallback; filter `list_all_documents`
  to one row per document; add doc_id/chunk_ordinal payload indexes.
- Add the point-layout marker to the metadata sidecar and a one-time clean
  rebuild when it mismatches or is missing over a non-empty collection.
- Add `get_chunk_counts` plus `delete_document_chunk_tail` and purge stale
  tail chunks of shrunk documents on every index path.

## Outcome

Chunked layout is lifecycle-safe: deletes remove every chunk, shrunk
documents leave no orphan tails, old stores rebuild automatically, and
retrieval-by-id stays byte-exact.

## Notes

The shrunk-tail hazard was found while writing tests, before any code
shipped.
