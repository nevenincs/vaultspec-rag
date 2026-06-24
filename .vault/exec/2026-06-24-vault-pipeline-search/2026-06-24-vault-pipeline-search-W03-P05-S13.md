---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S13'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---

# Implement the multiplicative per-(type x status) reweight function

## Scope

- `src/vaultspec_rag/search/_intent_rank.py`

## Description

- Authored `_intent_rank.py` with `intent_multiplier(result, profile)` computing the
  combined type x status weight (status axis applies to ADRs only; a legacy no-marker ADR
  maps to `unknown`; absent type/status default to a neutral 1.0).
- Authored `apply_intent_prior(results, profile)` multiplying each vault result's score in
  place, leaving codebase results untouched, then re-sorting descending; a no-op on an empty
  profile.

## Outcome

The prior reverses the live failure: with the orientation profile an accepted ADR scoring
0.46 outranks an exec record scoring 0.85 (0.85 x 0.4 = 0.34). `ruff` and `ty` pass.

## Notes

The function deliberately overrides semantic relevance on the type x status axis, per the
ADR; it is scoped to vault results and reads weights from inspectable config. Composition
into the searcher and intent selection follow in S14; the per-type cap in S15. No blockers.
