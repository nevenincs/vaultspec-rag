---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:aa9dbb19c7701d16377855271d128c0e76d779bb65a70815d7fd6c28285a8209'
step_id: 'S42'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Stream source hashing and enforce profile and per-rule source-byte ceilings before extraction

## Scope

- `src/vaultspec_rag/indexer/_chunk_worker.py`
- `src/vaultspec_rag/indexer/_preprocess_config.py`

## Description

- Stream source hashing without an unbounded identity read.
- Enforce the minimum effective profile and per-rule source-byte ceiling before extractor launch.

## Outcome

Oversized document inputs are refused before preprocessing consumes subprocess or GPU resources.

## Notes

The no-launch assertion uses a real marker-writing extractor.
