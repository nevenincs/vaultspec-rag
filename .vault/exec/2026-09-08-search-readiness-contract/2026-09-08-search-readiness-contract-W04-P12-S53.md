---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-14'
modified: '2026-09-14'
body_schema: 'body-v2'
body_hash: 'sha256:1918220211dd804de241e77dad7b9a2f5e4e6e0459b86c43edba8bb03e1825bc'
step_id: 'S53'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Prove immediate requests do not poll or wait and bounded waits add no global or GPU serialization

## Scope

- `src/vaultspec_rag/tests/test_search_readiness.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_search_readiness.py`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_search_readiness.py -q` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/test_search_readiness.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/test_search_readiness.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/test_search_readiness.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/tests/test_search_readiness.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
