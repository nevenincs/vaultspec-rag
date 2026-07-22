---
tags:
  - '#exec'
  - '#search-noise-filtering'
date: '2026-06-30'
modified: '2026-07-22'
step_id: 'S04'
related:
  - "[[2026-06-30-search-noise-filtering-plan]]"
---

# Add the post-rerank apply_domain_policy demote-or-hide pass, resolve exclude/only/include-domain, add the backfill loop with a filtered envelope note, and flip dedup-locales default on, with unit tests

## Scope

- `src/vaultspec_rag/search/_searcher.py`

## Description

- Add `search/_noise.py`: `NoisePolicy` value type and pure helpers
  `resolve_noise_policy` (profile + per-call overrides; include re-admits, hide
  beats demote), `partition_hard_domains` (post-query hide/only drop with path
  fallback + per-domain drop counts), `apply_domain_demotion` (penalty + re-sort).
- Add `_fetch_codebase_candidates`: pushes hide/only down to Qdrant, applies the
  glob + domain fallback post-query, and backfills by widening the fetch window
  until `top_k` is fillable, the index is exhausted, or a cap is hit - logging
  dropped-domain counts so depletion is never silent.
- Rewrite `_search_codebase_encoded` to resolve the policy, rerank the FULL
  surviving window (so demote can lift production above noise), apply demote then
  the prefer nudge then locale dedup, and annotate an optional `notes` mapping
  with `dropped_domains`.
- Flip `dedup_locales` to tri-state (`None` -> `dedup_locales_default`); thread
  `exclude_domains` / `only_domains` / `include_domains` / `notes` through
  `search_codebase` and `search_codebase_timed`.
- Add `tests/test_search_noise.py` (policy resolution, hard partition, demotion).
- Re-execute the candidate-budget branch so Qdrant-pushed hard-domain filters
  begin at the ordinary rerank window while Python path globs retain their
  wider initial window.
- Add real Qdrant-local coverage for the exact requested candidate counts and
  for survivor-depletion backfill over legacy rows without domain payloads.

## Outcome

242 unit tests passed across the touched suites; ruff and basedpyright clean on
all changed modules. Hard domain filters are pushdown (no depletion); the glob
path now backfills; demotion reorders the full window, not a pre-truncated page.

The 2026-07-22 re-execution corrected the pushed-filter amplification and passed
21 focused production-behavior tests. With the reranker path active and
`top_k=5`, a pushed hard-domain policy now requests 20 fused candidates instead
of 50, while an actual Python path glob still requests 50. Ruff format/check and
BasedPyright passed with no findings.

## Notes

The `notes["dropped_domains"]` envelope field is produced here but only surfaced
to callers in S06, where the facade/route/CLI/MCP signatures are threaded.

The re-execution preserved the missing-domain fallback: survivor depletion
widens the query window until the requested page is fillable, exhausted, or
capped. No compatibility branch or external-service behavior was added.
