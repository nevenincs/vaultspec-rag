---
tags:
  - '#exec'
  - '#search-noise-filtering'
date: '2026-06-30'
modified: '2026-07-22'
related:
  - "[[2026-06-30-search-noise-filtering-plan]]"
---

# `search-noise-filtering` `P02` summary

The query-time noise layer: domain pushdown filters, a demote-or-hide policy
pass, no-silent-depletion backfill, and a persistent per-project profile.

- Created: `src/vaultspec_rag/search/_noise.py`,
  `src/vaultspec_rag/tests/test_search_noise.py`
- Modified: `src/vaultspec_rag/store.py`,
  `src/vaultspec_rag/search/_searcher.py`, `src/vaultspec_rag/config.py`,
  `src/vaultspec_rag/tests/test_store_codebase.py`,
  `src/vaultspec_rag/tests/test_config.py`
- Created: `src/vaultspec_rag/tests/integration/test_search_noise_candidate_budget.py`

## Description

`_build_code_filter` gained `exclude_domains` / `only_domains` as Qdrant
`must_not` / `must` pushdown on the `domain` field. The searcher resolves a
`NoisePolicy` from the config profile plus per-call overrides, fetches with a
backfill loop (widen-and-re-query when a hard filter prunes below `top_k`,
logging dropped-domain counts), reranks the full surviving window, then demotes
noise domains by a configurable penalty. Locale dedup now defaults on. The
profile (`code_noise_hide_domains` / `code_noise_demote_domains` /
`code_noise_demote_penalty` / `dedup_locales_default`) is env- and
config-overridable, hide beating demote. Verified by policy, pushdown-builder,
and config unit tests.

The 2026-07-22 P02.S04 re-execution removed the accidental 10x initial fused
candidate budget for hard-domain constraints that Qdrant already pushes down.
Ordinary pushed-filter searches now begin at the normal reranker budget; real
Python path globs retain the wider budget, and legacy missing-domain rows still
trigger bounded widening only when fallback classification depletes survivors.
