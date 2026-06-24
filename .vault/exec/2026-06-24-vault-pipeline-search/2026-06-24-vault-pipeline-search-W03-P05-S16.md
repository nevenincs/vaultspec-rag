---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S16'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---




# Tune the weight profiles against the gold set and record the improvement over baseline

## Scope

- `src/vaultspec_rag/tests/quality/baseline.json`

## Description

- Renamed the config debug profile key to `debugging` so config, rubric, query set, and CLI
  share one intent vocabulary; threaded each query's declared intent into the harness search
  call.
- Re-ran the harness over a real-vault copy with the prior enabled and rewrote `baseline.json`
  to carry baseline vs with-intent-prior per-intent aggregates.
- Tightened the harness with the W03-deferred acceptance gate: an orientation
  Authoritative@3 floor and the named live regression (the canonical gpu-lock-scope query
  must rank the accepted ADR above the exec record).

## Outcome

The prior is proven on the real corpus. Orientation Authoritative@3 rose 0.50 -> 0.833,
which is the maximum achievable on the shipped set (the superseded-trap query has no grade-3
gold by construction); orientation NDCG@10 0.727 -> 0.738; debugging MRR unchanged at 0.50
(the ADR's debugging criterion); implementation unchanged. All three harness tests pass on
GPU in ~103s. `ruff` and `ty` pass.

## Notes

The weights already hit the orientation ceiling, so no further tuning was warranted; a larger
debugging query sample could refine that profile later (its MRR is already non-regressed).
This step also touched `config.py` (the profile rename) and `test_intent_ranking.py` (the
thresholds S05 deferred to W03), beyond the nominal `baseline.json` scope. No blockers.
