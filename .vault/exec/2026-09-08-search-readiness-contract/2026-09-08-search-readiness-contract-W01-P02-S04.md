---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:224b841302e17b7a3f099f6eb5019e3233eacb21212832457d2269d325580533'
step_id: 'S04'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Replace the empty-only classifier with per-source projection from canonical job generation controller integrity and collection evidence

## Scope

- `src/vaultspec_rag/server/_search_availability.py`

## Changes

- `M` `src/vaultspec_rag/server/_search_availability.py`
- `M` `.vault/plan/2026-09-08-search-readiness-contract-plan.md`
- `M` `.vault/index/search-readiness-contract.index.md`
- `A` `.vault/exec/2026-09-08-search-readiness-contract/2026-09-08-search-readiness-contract-W01-P02-S04.md`
- `verify:` `uv run --no-sync ruff format --check src/vaultspec_rag/server/_search_availability.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_rag/server/_search_availability.py` -> `pass`
- `verify:` `uv run --no-sync python -m ty check src/vaultspec_rag/server/_search_availability.py` -> `pass`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_search_availability.py src/vaultspec_rag/tests/test_http_search_errors.py -q --tb=short` -> `pass`
