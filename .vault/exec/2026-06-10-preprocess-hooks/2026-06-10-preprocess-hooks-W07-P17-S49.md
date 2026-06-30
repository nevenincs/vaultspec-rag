---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
step_id: 'S49'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add unit tests for entry_point success, bad reference, and timeout (D9 follow-up)

## Scope

- `src/vaultspec_rag/tests/test_preprocess_entry.py`

## Description

Added `test_preprocess_entry.py` (8 tests): `resolve_entry_point` ok / bad-format /
missing-attr; `main` emits JSON / returns non-zero on bad ref; and `run_preprocessor` with
an entry_point rule - ok (real subprocess), raising callable -> skip, unresolvable -> skip.
A real extractor module is written to a temp dir and exposed to the child via `PYTHONPATH`
(real env, no mocks).

## Outcome

8/8 pass; the entry_point form is exercised through the real subprocess runner.

## Notes

Setup-only fixture applied via `@pytest.mark.usefixtures` to keep ruff ARG clean.
