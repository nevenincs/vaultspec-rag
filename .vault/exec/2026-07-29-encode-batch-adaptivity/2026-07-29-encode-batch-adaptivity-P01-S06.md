---
tags:
  - '#exec'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S06'
related:
  - "[[2026-07-29-encode-batch-adaptivity-plan]]"
---

# add the encode token-budget and calibration settings with derivation defaults

## Scope

- `src/vaultspec_rag/config/_settings.py`

## Description

- add `embedding_encode_token_budget` (default 24000) and `embedding_encode_chars_per_token` (default 4) to `src/vaultspec_rag/config/_settings.py`, with the derivation documented in neighboring knob style
- add their positive-integer bounds entries in `src/vaultspec_rag/config/_schema.py`

## Outcome

Commit `25118c88`. Gates each exit 0; pytest 35 passed. Live config probe returns 24000 / 4.

## Notes

The bounds entries had to ride in this commit rather than the schema step: an import-time guard raises on a numeric default without a bounds entry.
