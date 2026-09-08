---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:87ff42da42be6be18e3feedc1538f4f468702e512b7a944c07229fa31ce61af6'
step_id: 'S34'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Mutation-prove the no-new-GPU-serialization concurrency guard

## Scope

- `src/vaultspec_rag/tests/test_service_search_diagnostics.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_service_search_diagnostics.py`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/test_service_search_diagnostics.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/test_service_search_diagnostics.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/test_service_search_diagnostics.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/tests/test_service_search_diagnostics.py` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_service_search_diagnostics.py -q` -> `pass`
- `verify:` `git diff --check` -> `pass`
