---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-11'
step_id: 'S05'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add unit tests with valid, invalid, newer-version, and older-version fixtures (D4, D5)

## Scope

- `src/vaultspec_rag/tests/test_preprocess_schema.py`

## Description

Added `test_preprocess_schema.py`: 14 unit tests - text-mode and units-mode validation,
units/text both-set and neither-set rejection, empty-units and empty-unit-text rejection,
unknown-field rejection at doc and unit level, missing-required-field rejection,
newer-schema-version rejection, string vs int locator values, locator range end, metadata
JSON values, and a JSON round-trip.

## Outcome

14/14 pass; ruff clean. Covers D4/D5 acceptance points.

## Notes

`schema_version < 1` is structurally impossible (Field ge=1), so the older-version branch
is a no-op until a v2 lands.
