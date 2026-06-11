---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S21'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Extend IndexResult with preprocess_skipped, preprocess_failed, and the preprocess_failures list (D11)

## Scope

- `src/vaultspec_rag/indexer/_vault_prep.py`

## Description

Extended `IndexResult` with `preprocess_skipped: int = 0` and
`preprocess_failures: list[str] = field(default_factory=list)` (default-valued so every
existing constructor stays valid). The full-index `IndexResult` is populated from the
per-run `self._prep_skips` accumulator (D11).

## Outcome

Skip counts and the `rel_path: reason` list are now first-class on the codebase index
result.

## Notes

The plan also named a `preprocess_failed` count; `on_error=fail` aborts the run (raises)
rather than counting, so a separate always-zero field was intentionally omitted - an honest
simplification recorded here.
