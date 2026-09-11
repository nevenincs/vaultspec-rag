---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:80a50e5c3f1b184bfada599c1e2e407dd59a637d6d0cdd30877936ec1e6a8c74'
step_id: 'S18'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Attach per-source facts and aggregate to success and require authoritative absence for empty success

## Scope

- `src/vaultspec_rag/server/_routes_search.py`

## Changes

- `M` `src/vaultspec_rag/server/_routes_search.py`
- `M` `src/vaultspec_rag/server/_search_availability.py`
- `verify:` `uv run ruff format --check src/vaultspec_rag/server/_routes_search.py src/vaultspec_rag/server/_search_availability.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/server/_routes_search.py src/vaultspec_rag/server/_search_availability.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/server/_routes_search.py src/vaultspec_rag/server/_search_availability.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_http_search_routing.py --disable-warnings` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_server.py --disable-warnings` -> `pass`
- `verify:` `git diff --check` -> `pass`

## Notes

The expected legacy assertions deferred to S21 remain: `test_search_availability.py` has 79 passing and 1 failing test whose pre-S18 expectation marks an observed successful collection unavailable without publication identity; `test_http_search_errors.py` has 24 passing and 1 failing test expecting a non-authoritative empty HTTP 200; and `test_service_search_diagnostics.py` has 16 passing and 1 failing test expecting empty-success diagnostics without authoritative absence.
