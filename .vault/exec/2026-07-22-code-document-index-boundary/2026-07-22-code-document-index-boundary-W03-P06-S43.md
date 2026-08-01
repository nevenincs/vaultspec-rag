---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:0a753f7775a7140efd7294effca45ea9dfb3f05e3e22ad0eb86b9d8868807c30'
step_id: 'S43'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Measure emitted encoded bytes and enforce aggregate output, chunk, payload, and weighted-queue ceilings

## Scope

- `src/vaultspec_rag/indexer/_preprocess_runner.py`
- `src/vaultspec_rag/indexer/_streaming.py`

## Description

- Measure encoded extractor output and revalidate cached output against the active ceiling.
- Bound aggregate generated chunks, payload bytes, and weighted queue slices.

## Outcome

Document execution now has enforceable per-file and aggregate resource accounting through storage publication.

## Notes

Weighted accounting includes embedding dimensions and rejects a slice that cannot fit the configured queue ceiling.
