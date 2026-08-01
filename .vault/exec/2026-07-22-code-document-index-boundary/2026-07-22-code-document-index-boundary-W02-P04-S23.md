---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:a1bb947ebffa8fdfe9acf2cee79a26f34966ecdd27ee94af6efb231f43f9e7cc'
step_id: 'S23'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Split worker output into source and document chunk result types without overloading `CodeChunk`

## Scope

- `src/vaultspec_rag/indexer/_chunk_worker.py`
- `src/vaultspec_rag/_store_models.py`

## Description

- Add a document-specific worker result carrying only `DocumentChunk` values.
- Keep source results typed as `CodeChunk` values.

## Outcome

Source and document worker products now cross an explicit model boundary.

## Notes

No unresolved work.
