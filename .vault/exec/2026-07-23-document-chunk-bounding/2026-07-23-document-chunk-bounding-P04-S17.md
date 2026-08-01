---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-24'
body_hash: 'sha256:64efcb51f947625c7ea1bae523b73d06c29bd2b10d31117e0b3d3ca49f2c222d'
step_id: 'S17'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# prove the unit text maximum-length rejection fails when the bound is removed and record both directions

## Scope

- `src/vaultspec_rag/tests/test_preprocess_schema.py`

## Description

- Remove `max_length` from the unit `text` field, run the rejection guard alone, observe it fail because the oversized payload was admitted, restore the bound, observe it pass - one uninterrupted sequence.

## Outcome

RED: `test_unit_text_above_maximum_is_rejected` failed with `Failed: DID NOT RAISE ValidationError` - the forbidden thing was admitted, the exact failure mode the guard exists to report. GREEN: bound restored, full schema suite passed (16 tests).

## Notes

The test asserts `string_too_long` on the `text` field location specifically, so a relocated or relabelled rejection cannot satisfy it; a comment in the test names the mutation it catches.
