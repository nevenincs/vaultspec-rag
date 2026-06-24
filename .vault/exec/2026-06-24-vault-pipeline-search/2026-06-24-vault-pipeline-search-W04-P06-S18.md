---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S18'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---

# Add doc-type union selection with audit included and index excluded

## Scope

- `src/vaultspec_rag/search/_validation.py`

## Description

- Added the `INDEXABLE_DOC_TYPES` union constant (adr, audit, exec, plan, reference,
  research; index excluded) and an `InvalidDocTypeError` (subclassing the existing
  filter-mismatch error so current handlers render it cleanly) to `search/_validation.py`.
- Validated the doc-type filter: a value is split on commas; any token outside the union
  (notably `index`) raises with a clear message listing the allowed set.
- Taught the store `_build_filter` to expand a comma-separated `doc_type` into a Qdrant
  `MatchAny` union, keeping a single value as an exact `MatchValue`.

## Outcome

A doc-type union is now expressible as `--doc-type adr,plan` or the inline `type:adr,plan`
token, with `audit` in and `index` rejected. Verified: `adr,plan` validates; `index` is
rejected with the allowed-set message. `ruff` and `ty` pass.

## Notes

The comma-list form keeps the CLI surface single-valued, avoiding a new function argument
that would breach the frozen `max-args` ratchet (the same constraint that shaped the intent
token in S17). No blockers.
