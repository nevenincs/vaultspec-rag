---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S14'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---




# Compose the intent prior post-rerank and select the active profile in vault search

## Scope

- `src/vaultspec_rag/search/_searcher.py`

## Description

- Added `_resolve_intent_profile` (reads config: returns None when ranking is disabled or the
  intent name has no profile) and `_apply_intent_prior` to the searcher.
- Composed the prior immediately after `rerank_with_graph` in `_search_vault_encoded`, so the
  type x status signal is primary and the graph nudges break ties within the reweighted order.
- Threaded an `intent: str | None` parameter through `search_vault`, `search_vault_timed`,
  and `_search_vault_encoded`; a None intent falls back to the configured default.

## Outcome

The vault search path now applies the intent prior by default (orientation). `ruff` and `ty`
pass after an import-sort autofix. Full GPU verification of the ranking improvement is done in
S16 against the W01 baseline.

## Notes

The prior composes after the GPU section and outside the lock, honoring
`gpu-lock-wraps-forward-passes-only`. Per-type cap is added in S15. No blockers.
