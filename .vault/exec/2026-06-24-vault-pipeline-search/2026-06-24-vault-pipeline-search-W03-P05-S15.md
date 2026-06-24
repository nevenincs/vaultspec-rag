---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S15'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---

# Implement the per-type result cap to prevent one type crowding the top-k

## Scope

- `src/vaultspec_rag/search/_intent_rank.py`

## Description

- Added `apply_type_cap(results, cap)` to `_intent_rank.py`: an order-preserving filter that
  keeps at most `cap` vault results per doc_type (codebase results never capped; `cap <= 0`
  disables it).
- Wired the cap into the searcher `_apply_intent_prior` after the prior re-sort, reading
  `vault_intent_type_cap` from config, so the cap bounds the returned page before top_k
  truncation.

## Outcome

The cap collapses a run of one type without touching the others: a list of six exec results
plus one ADR is capped to four exec and the ADR. `ruff` and `ty` pass.

## Notes

The cap is uniform across types (configurable); for a debugging page that wants many exec
records, an operator can raise `vault_intent_type_cap`. End-to-end tuning and verification
against the baseline follow in S16. No blockers.
