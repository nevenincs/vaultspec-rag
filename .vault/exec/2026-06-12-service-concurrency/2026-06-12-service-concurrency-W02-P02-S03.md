---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
step_id: 'S03'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Chunk vault documents with the heading-aware TextSplitter into one point per chunk carrying doc metadata, ordinal-derived stable IDs, and embed text separated from stored content

## Scope

- `src/vaultspec_rag/indexer/_vault_indexer.py`

## Description

- Add `split_document` heading-aware chunker (markdown `TextSplitter`, no
  overlap, one chunk minimum, ordinal-0 carries the full body) in
  `_vault_prep.py`.
- Expand documents into chunks inside the vault streaming helper; embed text
  is title + chunk text; the helper returns per-document chunk counts.
- Add the `vault_chunk_chars` knob (default 3000) with its env var.

## Outcome

Long documents now produce one point per heading-aware chunk; the embedding
horizon limitation (content past 8000 chars invisible) is gone. Verified by
unit tests and the GPU integration suite.

## Notes

Landed in commit 3fe5cf5 with the other retrieval-quality steps.
