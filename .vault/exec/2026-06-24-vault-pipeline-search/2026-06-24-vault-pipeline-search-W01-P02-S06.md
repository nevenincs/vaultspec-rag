---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S06'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---




# Capture and commit the baseline ranking report on the current reranker

## Scope

- `src/vaultspec_rag/tests/quality/baseline.json`

## Description

- Ran the intent-ranking harness against a hermetic copy of the project vault on the real
  GPU (694 documents indexed) using the current bare-reranker ranking.
- Computed per-query role-aware metrics and per-intent aggregates, and wrote them to
  `baseline.json` (ranking tag, per-intent aggregates, and the full per-query report).

## Outcome

Baseline captured. Per-intent aggregates on the current ranking:

- orientation: mean NDCG@10 0.7266, Authoritative@3 rate 0.50 (only half of orientation
  queries surface the accepted ADR in the top 3 - the headline gap the W03 prior must close,
  target near 1.0).
- debugging: mean NDCG@10 0.50, mean MRR@grade-3 0.50.
- implementation: mean NDCG@10 0.8906, mean MRR@grade-3 1.0.

These are the numbers Wave W03 must improve (orientation especially) without regressing
debugging or implementation.

## Notes

Captured via a one-shot script in the scratchpad reusing the harness `run_evaluation`; no
script was added to the repo (the artifact is `baseline.json`). The index lacked the new
status field (W02 not yet landed), which is correct - the baseline is the current pipeline,
and gold grades come from the rubric, not the index. No blockers.
