---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:873d471fb8d179c8168b77858c0d095e49f096a6a91da8935879b07f11bbe056'
step_id: 'S19'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Map typed failure status and emit Retry-After only from a canonical future deadline

## Scope

- `src/vaultspec_rag/server/_routes_search.py`

## Changes

- `M` `src/vaultspec_rag/server/_routes_search.py`
- `verify:` `uv run ruff format --check src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_http_search_routing.py --disable-warnings` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_server.py --disable-warnings` -> `pass`
- `verify:` `git diff --check` -> `pass`

## Notes

No current canonical response fact carries an enforced future capacity-reset deadline, so capacity remains HTTP 503 and `Retry-After` is omitted rather than inferred.
