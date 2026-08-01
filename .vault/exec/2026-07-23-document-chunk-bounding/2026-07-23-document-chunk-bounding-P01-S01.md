---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-24'
body_hash: 'sha256:ebfd9f28bdb45b9b5a4cc3635686105bdf0d7099a4586edf03a86c2d5862b01c'
step_id: 'S01'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# add an explicit maximum length to the unit text field so the schema stops advertising an unbounded payload

## Scope

- `src/vaultspec_rag/indexer/_preprocess_schema.py`

## Description

- Add `UNIT_TEXT_MAX_CHARS = 1_000_000` and apply it as `max_length` on the unit `text` field in `src/vaultspec_rag/indexer/_preprocess_schema.py`.
- Reword the `PreprocUnit` and `PreprocOutput` docstrings so "pre-chunked" is described as hook intent the indexer still bounds and splits, not a trusted size guarantee.

## Outcome

Schema stops advertising an unbounded payload; text-at-maximum accepted, text-above-maximum rejected with `string_too_long` bound to the `text` field.

## Notes

The bound is deliberately generous: it makes the contract honest and rejects the pathological payload; splitting (not this bound) handles every unit above the model window.
