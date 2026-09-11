---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:6b96c4d800eb836d607e888bd742c129af7a7edc69eb0a087015212ddc66c353'
step_id: 'S06'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Add explicit rebuild-required evidence and cover current updating unavailable unverifiable rebuild capacity authority and bounded scenarios

## Scope

- `src/vaultspec_rag/server/_search_availability.py and src/vaultspec_rag/tests/test_search_availability.py`

## Changes

- `M` `src/vaultspec_rag/server/_search_availability.py`
- `M` `src/vaultspec_rag/tests/test_search_availability.py`
- `M` `.vault/plan/2026-09-08-search-readiness-contract-plan.md`
- `M` `.vault/index/search-readiness-contract.index.md`
- `A` `.vault/exec/2026-09-08-search-readiness-contract/2026-09-08-search-readiness-contract-W01-P02-S06.md`
- `verify:` `uv run --no-sync ruff format --check src/vaultspec_rag/server/_search_availability.py src/vaultspec_rag/tests/test_search_availability.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_rag/server/_search_availability.py src/vaultspec_rag/tests/test_search_availability.py` -> `pass`
- `verify:` `uv run --no-sync python -m ty check src/vaultspec_rag/server/_search_availability.py src/vaultspec_rag/tests/test_search_availability.py` -> `pass`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_search_availability.py -q --tb=short` -> `pass`
