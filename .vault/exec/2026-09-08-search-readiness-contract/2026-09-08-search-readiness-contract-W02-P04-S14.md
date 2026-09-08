---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:8172cf743705269261f3961869f3f6b267469cf778675bfe694cc6136d5bb732'
step_id: 'S14'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Add immediate-default and bounded request policy capture stable source targets enforce maximum wait and preserve cancellation

## Scope

- `src/vaultspec_rag/server/_routes_search.py`

## Changes

- `M` `src/vaultspec_rag/server/_routes_search.py`
- `M` `.vault/plan/2026-09-08-search-readiness-contract-plan.md`
- `M` `.vault/index/search-readiness-contract.index.md`
- `A` `.vault/exec/2026-09-08-search-readiness-contract/2026-09-08-search-readiness-contract-W02-P04-S14.md`
- `verify:` `uv run ruff format --check src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_http_search_routing.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_http_search_errors.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_server.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_search_readiness.py` -> `pass`
