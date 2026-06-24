# Intent-aware ranking: A/B delta report

This report records the per-intent ranking metrics before and after the
intent-conditioned type x status prior (ADR `vault-pipeline-search`, decisions
D2-D4), measured by the harness in `tests/integration/test_intent_ranking.py`
against a hermetic copy of the project `.vault/` on the real GPU index (694
documents). Gold grades are rubric-derived (`tests/quality/rubric.py`); the
machine-readable source is `tests/quality/baseline.json`.

Metrics are reported per declared intent and never blended. The headline is the
orientation **Authoritative@3 rate** (the share of orientation queries that
surface a grade-3 accepted ADR in the top 3) and role-aware **NDCG@10**.

| Intent | Metric | Baseline (bare reranker) | With intent prior | Delta |
| --- | --- | --- | --- | --- |
| orientation | Authoritative@3 rate | 0.500 | **0.833** | +0.333 |
| orientation | mean NDCG@10 | 0.7266 | 0.7382 | +0.0116 |
| debugging | mean MRR@grade-3 | 0.500 | 0.500 | 0.000 |
| debugging | mean NDCG@10 | 0.500 | 0.484 | -0.016 |
| implementation | mean MRR@grade-3 | 1.000 | 1.000 | 0.000 |
| implementation | mean NDCG@10 | 0.8906 | 0.8906 | 0.000 |

## Reading the result

- **Orientation (the target):** Authoritative@3 rose from 0.500 to 0.833. That
  0.833 is the achievable ceiling on the shipped query set, not a shortfall: one
  orientation query is the deliberate superseded-ADR trap, whose gold tops out
  at grade 2 (it has no grade-3 document by construction), so it can never score
  on a grade-3 metric. Every orientation query that *can* surface an accepted
  ADR in the top 3 now does. The named live regression - "decision on gpu lock
  scope" must rank the accepted `service-concurrency` ADR above the exec record
  that implements it - passes.

- **Debugging:** the ADR's debugging acceptance criterion is MRR, which is
  unchanged at 0.500 (no regression). The NDCG@10 dip of 0.016 is within noise
  for a two-query sample and does not breach any gate; a larger debugging query
  set would let that profile be tuned with more signal.

- **Implementation:** unchanged, as expected - no implementation profile ships,
  so those queries keep the bare-reranker ordering, which was already strong
  (NDCG 0.89, MRR 1.0).

- **No-regress floor:** the existing needle-precision quality probe is untouched
  by the prior (it composes after rerank, on the grouped result list).

## Provenance

Baseline captured before the prior landed; the after-figures were captured with
the orientation/debugging profiles active and the per-type cap at its default.
Both runs use real GPU + real Qdrant + real models, per the project's
no-mock / real-inference mandate.
