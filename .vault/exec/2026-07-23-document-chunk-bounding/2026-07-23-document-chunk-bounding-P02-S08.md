---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S08'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# pass the fragment discriminator from chunk construction into point identity derivation

## Scope

- `src/vaultspec_rag/indexer/_chunk_worker.py`

## Description

- Pass the enumerated fragment ordinal from the units-branch fragment loop into `document_point_id` in `src/vaultspec_rag/indexer/_chunk_worker.py`.

## Outcome

Chunk construction and identity derivation agree on the discriminator; enumeration order is deterministic so unchanged files replay to identical ids.

## Notes
