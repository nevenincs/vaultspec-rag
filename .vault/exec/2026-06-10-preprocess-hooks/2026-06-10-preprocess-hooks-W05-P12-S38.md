---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
step_id: 'S38'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add coverage-count assertions for a failing preprocessor skip/fail surfacing (D11)

## Scope

- `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`

## Description

Added a coverage-count test: a rule whose command exits non-zero (`on_error=skip`) against
a `broken.pdf` full-indexes to `IndexResult.preprocess_skipped == 1` with the file named in
`preprocess_failures` - proving a failed extraction is a surfaced count, never a silent gap
(D11).

## Outcome

Passes in ~22s (no search, so no reranker). Confirms the no-swallow failure-visibility
contract end-to-end.

## Notes

This is the lightest integration test and was used to confirm the core pipeline
independently of the reranker.
