---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:25cd0ca04dddcb30c0224fa9ef7eaf63947658c7b5eff36171730419b70476ce'
step_id: 'S24'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Classify every requested source and retain constituent failures beside useful combined results

## Scope

- `src/vaultspec_rag/_public_search.py`

## Changes

- `M` `src/vaultspec_rag/_public_search.py`
- `verify:` `uv run ruff format --check src/vaultspec_rag/_public_search.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/_public_search.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/_public_search.py src/vaultspec_rag/search/_outcomes.py` -> `pass`
- `verify:` `git diff --check` -> `pass`

## Notes

The staged S26 outcome suite remains at 157 passing and 2 failing tests because its legacy fixtures do not yet supply the source facts required by S23.
