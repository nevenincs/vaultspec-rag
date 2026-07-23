---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S02'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# derive the character split budget from the dense model sequence window by a declared chars-per-token ratio instead of a literal

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Add `document_chunk_chars_per_token` (3) and `document_chunk_overlap_chars` (256) config defaults with rationale comments in `src/vaultspec_rag/config.py`.
- Add validated properties `document_chunk_chars_per_token`, `document_chunk_overlap_chars`, and derived `document_chunk_chars` = `embedding_max_seq_length` x ratio.
- Reject an overlap at or above the derived budget at property resolution.

## Outcome

The split budget derives from the dense model token window by a declared conservative chars-per-token ratio (2048 x 3 = 6144 chars by default), never a hardcoded literal, so it tracks a model change.

## Notes

The derivation is torch-free (pure config arithmetic), keeping the chunking path safe for CPU-only spawn workers.
