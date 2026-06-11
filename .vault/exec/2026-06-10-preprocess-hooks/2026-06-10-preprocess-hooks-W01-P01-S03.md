---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S03'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add unit tests for loading, ordering, ignore-composition, and error policy with real toml fixtures (D1, D2, D3)

## Scope

- `src/vaultspec_rag/tests/test_preprocess_config.py`

## Description

Added `test_preprocess_config.py`: 13 unit tests over real `.vaultragpreprocess.toml`
fixtures written to `tmp_path` (no mocks) - absent-config empty result, single-rule
match, priority-then-file-order determinism, equal-priority tie-break, options carry,
entry_point drop (v1), command/entry_point XOR, invalid `on_error` drop with valid-rule
survival, malformed-TOML degrade, strict-mode raises, negative-timeout reject, and
rule picklability.

## Outcome

13/13 pass; ruff clean. Covers D1/D2/D3 acceptance points.

## Notes

Picklability test guards the W03.P05 worker-threading requirement.
