---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-24'
body_hash: 'sha256:0f11382cf6483efb3e4f46970cb7438bfb9c729da449a35f312866e8d5cd9850'
step_id: 'S05'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# give the document splitter configuration a non-zero overlap so a fragment boundary does not sever context

## Scope

- `src/vaultspec_rag/indexer/_chunk_worker.py`

## Description

- Give the shared document splitter a non-zero overlap (`document_chunk_overlap` on `ChunkExecutionPolicy`, 256 chars by default, config-derived on the production path).

## Outcome

A fragment boundary no longer severs context mid-sentence; the gapless-coverage test tolerates and exercises the overlap.

## Notes

The raw-text branch previously split with `chunk_overlap=0`; both document branches now share the overlap. Chunk-shape changes are rebuild-signalled by the epoch work in the same plan.
