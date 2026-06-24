---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S05'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---




# Add the quality-marked integration harness driving a real index against the gold set

## Scope

- `src/vaultspec_rag/tests/integration/test_intent_ranking.py`

## Description

- Authored `test_intent_ranking.py`: a quality-marked harness that loads the labeled query
  set, builds a `{doc_id: grade}` gold map, and scores each query's ranked ids with the
  role-aware metrics per declared intent (Authoritative@3 for orientation, MRR for the rest).
- Added a session fixture `real_vault_searcher` that copies the project `.vault/` (excluding
  the on-disk index data and locks) into a temp root, indexes it on the real GPU, and yields
  a `VaultSearcher`, so the gate runs against the real competing corpus without touching the
  project index or the running service's store lock.
- Exposed `run_evaluation(searcher)` as reusable orchestration so baseline and post-prior
  rankings score through the same routine.
- Added a structural gate asserting every query yields well-formed, in-range per-intent
  metrics.

## Outcome

Harness builds and is `ruff`/`ty` clean. Per the no-skip/no-xfail mandate, the strict
per-intent thresholds and the named orientation regression are deferred to Wave W03, where
the intent prior makes them pass; the live GPU run that exercises the fixture is performed
in S06 when capturing the baseline.

## Notes

The strict thresholds are intentionally not asserted yet because the bare reranker fails
them by design (that is the documented baseline). No blockers.
