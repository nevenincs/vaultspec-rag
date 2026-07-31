---
tags:
  - '#exec'
  - '#vault-true-incremental'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S06'
related:
  - "[[2026-07-25-vault-true-incremental-plan]]"
---

# Classify a body-digest delta as re-chunk and re-embed, preserving the current indexing path for that branch unchanged

## Scope

- `src/vaultspec_rag/indexer/_vault_indexer.py`

## Description

- Add `_classify_documents()` and `_VaultClassification` to
  `src/vaultspec_rag/indexer/_vault_indexer.py`, splitting candidates into a
  re-embed set and a payload-only set.
- Route the re-embed set into the existing `to_index_ids` union so it reaches
  `_parse_documents` and the streaming encode seam exactly as before.
- Report its size as `IndexResult.updated`, unchanged in meaning.

## Outcome

The expensive branch is untouched. A document whose body moved parses, chunks,
encodes, and upserts through the same path it always did; the only difference is
which documents arrive there. That was the point of keeping this Step separate -
the branch that must keep working is the one worth not rewriting.

`classify()` returns a body delta when both digests moved, not a metadata one.
Stale vectors are the more expensive error of the two, so the body decides.

## Notes

`IndexResult.updated` keeps its meaning of "re-embedded", and the new
`payload_updated` field carries the cheap branch separately. Collapsing them
would have hidden the difference between a run that reached the GPU and one that
did not, which is the entire distinction this plan draws.
