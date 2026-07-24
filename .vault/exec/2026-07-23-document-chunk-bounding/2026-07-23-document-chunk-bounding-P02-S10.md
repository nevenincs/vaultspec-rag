---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-24'
step_id: 'S10'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# add a test asserting fragment ids are stable across a repeated run of an unchanged unit so ledger replay stays idempotent

## Scope

- `src/vaultspec_rag/tests/test_chunk_worker_parity.py`

## Description

- Add `test_fragment_ids_are_stable_across_repeated_runs`: two runs over identical units (one splitting, one not; ordinal and locator branches both covered) must produce identical id sequences.
- Assert the first id of each branch reproduces from `document_point_id`'s declared inputs.

## Outcome

Ledger replay stays idempotent: byte-identical fragment ids across repeated runs of an unchanged unit.

## Notes

Same module deviation as S09 (`src/vaultspec_rag/tests/test_document_unit_bounding.py`).
