---
tags:
  - '#exec'
  - '#search-noise-filtering'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S01'
related:
  - "[[2026-06-30-search-noise-filtering-plan]]"
---

# Create a worker-safe pure classify_domain(path) returning prod/tests/docs/locale/generated/vendored/worktree, supersede the prefer classifier to consume it, with unit tests

## Scope

- `src/vaultspec_rag/_domain.py`

## Description

- Add `src/vaultspec_rag/_domain.py`: a dependency-free `classify_domain(path)`
  returning `prod | tests | docs | locale | generated | vendored | worktree`,
  with `DOMAINS` and `NOISE_DOMAINS` exports.
- Precedence is worktree > vendored > generated > tests > locale > docs > prod
  so a clone or third-party tree dominates whatever it nests.
- Repoint `_classify_chunk_type` (the `--prefer` classifier) at
  `classify_domain` as a three-category projection, removing the duplicate
  test/docs lookup tables; drop the now-unused `fnmatch` import.
- Add `tests/test_domain.py` covering each domain, precedence, Windows
  separators, and the data-file-is-not-locale guard.

## Outcome

`pytest test_domain.py test_search_unit.py` -> 58 passed. The module imports
only stdlib (worker-safe, torch-free) and is the single source of truth shared
by the index writer and the query-time fallback.

## Notes

`_classify_chunk_type`'s three-category contract is preserved exactly (all prior
`--prefer` tests still pass); the new domains are additive and surface only
through the noise policy added in later Steps.
