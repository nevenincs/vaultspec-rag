---
tags:
  - '#plan'
  - '#index-lifecycle-consolidation'
date: '2026-07-25'
modified: '2026-07-25'
tier: L1
related:
  - '[[2026-07-25-index-lifecycle-consolidation-adr]]'
  - '[[2026-07-25-index-lifecycle-consolidation-research]]'
---

# `index-lifecycle-consolidation` plan

- [ ] `S01` - Extract the shared index run lifecycle into its own module, owning the activity stamp, the event triple, and the incremental mode label; `src/vaultspec_rag/indexer/_index_lifecycle.py`.
- [ ] `S02` - Route the codebase and vault entry points through the shared lifecycle, preserving event fields, ordering, and emitting logger identity; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `S03` - Extract the document run bodies and route both document entry points through the shared lifecycle so the stamp and the events arrive by construction; `src/vaultspec_rag/indexer/_document_indexer.py`.
- [ ] `S04` - Add the cross-indexer parity test binding every entry point to the shared lifecycle, and mutation-prove each guard can fail; `src/vaultspec_rag/tests/test_index_lifecycle_parity.py`.

## Description

## Steps

## Parallelization

## Verification
