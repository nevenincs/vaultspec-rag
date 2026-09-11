---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:ced0f1da2ba5809664ff700e56b9c2c78d4b01cbea4cf844e59aeb60aa42750f'
step_id: 'S31'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Map storage duration and refusal to storage-owned outcomes without guessing index state

## Scope

- `src/vaultspec_rag/server/_routes_search.py`

## Changes

- `M` `src/vaultspec_rag/server/_routes_search.py`
- `verify:` `uv run ruff format --check src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_http_search_routing.py src/vaultspec_rag/tests/test_http_search_errors.py src/vaultspec_rag/tests/test_service_search_diagnostics.py -q` -> `pass`
- `verify:` `git diff --check` -> `pass`

## Notes

Storage duration remains timing-only because the route phase can aggregate multiple calls and therefore has no single enforced wait bound. Backend-unavailable responses have no canonical future deadline and emit no `Retry-After` header.
