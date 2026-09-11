---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:b7abee4a750b9ec8f0f45b16a20a619e61256b482d8bae883121d60eea6077d7'
step_id: 'S20'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Replace legacy availability envelopes with canonical code retry wait evidence and remediation

## Scope

- `src/vaultspec_rag/server/_search_availability.py`

## Changes

- `M` `src/vaultspec_rag/_search_state.py`
- `M` `src/vaultspec_rag/server/_routes_search.py`
- `M` `src/vaultspec_rag/server/_search_availability.py`
- `verify:` `uv run ruff format --check src/vaultspec_rag/_search_state.py src/vaultspec_rag/server/_routes_search.py src/vaultspec_rag/server/_search_availability.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/_search_state.py src/vaultspec_rag/server/_routes_search.py src/vaultspec_rag/server/_search_availability.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/_search_state.py src/vaultspec_rag/server/_routes_search.py src/vaultspec_rag/server/_search_availability.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_http_search_routing.py --disable-warnings` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_server.py --disable-warnings` -> `pass`
- `verify:` `git diff --check` -> `pass`

## Notes

The expected legacy assertions deferred to S21 remain: `test_search_availability.py` has 78 passing and 2 failing tests whose pre-S18/S20 expectations mark an observed successful collection unavailable without publication identity and decline a collection disappearance without a matching job; `test_http_search_errors.py` has 24 passing and 1 failing test expecting a non-authoritative empty HTTP 200.
