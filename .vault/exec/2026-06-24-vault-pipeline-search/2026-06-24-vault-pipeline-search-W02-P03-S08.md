---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S08'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---

# Carry status on VaultDocument and VaultChunk and write it to the Qdrant payload

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Added a `status: str = ""` field to `VaultDocument` and `VaultChunk` (placed after the
  non-default fields to satisfy dataclass ordering), with docstring entries.
- Wrote `status` into the Qdrant payload on both the document and chunk upsert paths.
- Wired `prepare_document` to call `_extract_status(body)` and pass `status`, and
  `split_document` to propagate `doc.status` onto every chunk.
- Confirmed the search-return path passes the whole payload through
  (`row = dict(point.payload)`), so `status` (and the already-stored `related`) reach result
  rows with no further store change.

## Outcome

End-to-end verified on real documents: the service-concurrency ADR prepares with status
`accepted`, a cleaned title, and its four related links; the head chunk carries the status;
the legacy `# ADR:` document resolves to empty status (unknown). `ruff` and `ty` pass.

## Notes

`status` is now in the payload but not yet on `SearchResult`; S09 adds the field to the
result model and S10 maps it from the row. A reindex (S11) is required before stored
documents carry the new payload field. No blockers.
