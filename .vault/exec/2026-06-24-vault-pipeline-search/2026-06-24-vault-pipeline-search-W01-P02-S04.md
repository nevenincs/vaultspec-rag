---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S04'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---




# Implement role-aware NDCG, Authoritative-at-k, MRR, and role-precision metrics

## Scope

- `src/vaultspec_rag/tests/quality/metrics.py`

## Description

- Authored `metrics.py` with pure role-aware ranking metrics over a ranked doc_id list
  and a graded gold mapping: `ndcg_at_k` (gain = grade, the headline), `rank_of_first_grade`,
  `authoritative_at_k` (orientation grade-3-in-top-k signal), `mrr_at_first_grade` (debugging
  signal), and `role_precision_at_k` (sanity guard).
- Used exponential gain `2**grade - 1` with `log2(rank+1)` discount; documents absent from
  gold are grade 0; ideal-DCG-zero guarded to return 0.0.
- Moved the typing-only `collections.abc` imports under `TYPE_CHECKING` to satisfy lint.

## Outcome

Pure, importable metrics module. Verified by smoke test: a correctly-ordered ranking scores
NDCG 1.0 while the inverted ranking scores 0.68; `authoritative_at_k` separates the two; the
debugging MRR and role-precision behave as defined. `ruff` and `ty` pass.

## Notes

Distinct from the pre-existing `tests/metrics.py` (performance metrics) by living under the
`tests/quality/` namespace. No blockers.
