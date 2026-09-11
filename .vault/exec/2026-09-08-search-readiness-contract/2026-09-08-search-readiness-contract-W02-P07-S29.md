---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:4e8d0b9ea8075fb16b1d9b4b1459320720ce7a750b91d2be112f662858290c31'
step_id: 'S29'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Measure search-limiter and compute-ticket waits separately from service duration

## Scope

- `src/vaultspec_rag/server/_routes_search.py`

## Changes

- `M` `src/vaultspec_rag/server/_routes_search.py`
- `verify:` `uv run ruff format --check src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_http_search_routing.py src/vaultspec_rag/tests/test_http_search_errors.py src/vaultspec_rag/tests/test_service_search_diagnostics.py src/vaultspec_rag/tests/test_search_activity.py -q` -> `pass`
- `verify:` `git diff --check` -> `pass`

## Notes

Search-limiter and compute-ticket elapsed durations remain timing-only because those boundaries have no enforced server-side wait bound. Only the bounded search-activity admission wait is emitted as a canonical wait observation.
