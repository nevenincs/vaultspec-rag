---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S38'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Apply the source decoder only after code admission and bypass it for extractor-owned document input

## Scope

- `src/vaultspec_rag/indexer/_chunk_worker.py`
- `src/vaultspec_rag/indexer/_content_policy.py`

## Description

- Route extractor-owned document bytes directly to document preprocessing.
- Decode raw source only after the resolved policy admits it as code.

## Outcome

Binary document inputs no longer enter the source decoder, while admitted raw code retains explicit decoder failure outcomes.

## Notes

Verified with a real binary input and subprocess extractor.
