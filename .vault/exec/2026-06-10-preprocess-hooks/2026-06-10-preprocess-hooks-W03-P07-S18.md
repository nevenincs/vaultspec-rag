---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S18'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add the preproc_docs collection schema and payload indexes with the split locator fields (D12)

## Scope

- `src/vaultspec_rag/store.py`

## Description

**Storage-model decision (deviation from ADR D12, user-approved):** rather than a separate
`preproc_docs` Qdrant collection, preprocessed units are stored as first-class entries in
the existing `codebase_docs` collection with extended optional payload. This keeps the
single GPU consumer and embed/upsert/search seam untouched (the rule-critical invariant)
and was the smaller, fully-testable path to a working v1; the separate collection is a
documented follow-up. Extended `CodeChunk` (and the upsert payload) with `source_path`,
`preprocessor_id`, `anchor`, `locator_kind`, `locator_value_int`, `locator_value_str`, and
added payload indexes (preprocessor_id/locator_kind/locator_value_str KEYWORD,
locator_value_int INTEGER) - the split locator keeps a typed index per value kind (D12).

## Outcome

Preproc payload persists and is filterable; ordinary chunks carry nulls. No new collection,
no consumer changes.

## Notes

Deviation surfaced to and approved by the user before implementation; flagged as a
follow-up (separate collection) for docs and a future ADR amendment.
