---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:810b60cca46980de37afd7a8bc79d449c4847c462993aff955e52696d9df3b80'
step_id: 'S15'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Add the bounded freshness-wait maximum to canonical configuration and settings projection

## Scope

- `src/vaultspec_rag/config`

## Changes

- `M` `src/vaultspec_rag/config/_types.py`
- `M` `src/vaultspec_rag/config/_schema.py`
- `M` `src/vaultspec_rag/config/_settings.py`
- `M` `src/vaultspec_rag/server/_routes_search.py`
- `M` `.vault/plan/2026-09-08-search-readiness-contract-plan.md`
- `M` `.vault/index/search-readiness-contract.index.md`
- `A` `.vault/exec/2026-09-08-search-readiness-contract/2026-09-08-search-readiness-contract-W02-P04-S15.md`
- `verify:` `uv run ruff format --check src/vaultspec_rag/config/_types.py src/vaultspec_rag/config/_schema.py src/vaultspec_rag/config/_settings.py src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/config/_types.py src/vaultspec_rag/config/_schema.py src/vaultspec_rag/config/_settings.py src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/config/_types.py src/vaultspec_rag/config/_schema.py src/vaultspec_rag/config/_settings.py src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_config.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_http_search_routing.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_http_search_errors.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_server.py` -> `pass`

## Notes

`uv run pytest -q src/vaultspec_rag/tests/test_configuration_doc.py` had 5 passing and 2 failing tests: the new environment variable remains intentionally undocumented until S58, and the unrelated pre-existing integrity-auto-repair default mismatch remains unchanged.
