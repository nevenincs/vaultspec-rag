---
tags:
  - '#exec'
  - '#search-noise-filtering'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S07'
related:
  - "[[2026-06-30-search-noise-filtering-plan]]"
---

# Add a performance benchmark replaying the fixed query set against the live index asserting a noise@k reduction versus baseline, reindex and re-measure, and document the noise controls

## Scope

- `src/vaultspec_rag/tests/benchmarks/bench_search_noise.py`

## Description

- Add `tests/benchmarks/bench_search_noise.py` (`@pytest.mark.performance`): a
  controlled polyglot corpus (prod modules shadowed by test, doc, four-locale,
  vendored, generated, and worktree-clone copies), indexed with real GPU
  embeddings into a real Qdrant collection, measuring top-k domain composition
  with the noise profile off vs on.
- Add a `VAULTSPEC_RAG_RERANKER_ENABLED` env knob so the benchmark runs
  deterministically without the CrossEncoder (the policy is rerank-independent),
  sidestepping an intermittent Windows transformers model-load fault.
- Document the noise controls (domain tokens, default behaviour, dedup default)
  in the search guide and the four new config knobs in the config guide.

## Outcome

Verified improvement on the controlled corpus (rerank on, headline numbers):
noise@10 0.88 -> 0.40, production results 7 -> 36 (5x), locale hits 26 -> 6
(dedup), generated 6 -> 0 (hidden), worktree clones absent (index-time
exclusion). The deterministic reranker-off benchmark asserts hidden domains
vanish entirely, total noise drops by at least 0.2, and the production share
rises - 3 passed. Live-repo baseline recorded separately at 70.8% noise@12 and
44.2% duplicates.

Full gate clean: ruff over all `src/`, basedpyright over the full package
(0 errors), and mdformat plus pymarkdown on every authored doc.

## Notes

The benchmark disables the reranker to dodge a pre-existing, intermittent Windows
CrossEncoder-load access violation (already mitigated for the service via
`HF_DEACTIVATE_ASYNC_LOAD`); the noise policy runs after rerank and is
unaffected, so the measurement is faithful. GPU tests run locally, not in CI.
