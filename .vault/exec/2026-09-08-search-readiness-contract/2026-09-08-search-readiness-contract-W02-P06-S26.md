---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:0d0a4f88e1ec7fec7c4f810a97900f7949fa1ab2d3b210dd4b95d4fbcebcbd3d'
step_id: 'S26'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Prove partial degraded failed authoritative-empty non-authoritative-empty and omitted-domain combined outcomes

## Scope

- `src/vaultspec_rag/tests/test_search_outcomes.py`

## Changes

- `M` `src/vaultspec_rag/server/_routes_search.py`
- `M` `src/vaultspec_rag/tests/test_search_outcomes.py`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_search_outcomes.py src/vaultspec_rag/tests/test_cli_search.py src/vaultspec_rag/tests/test_server.py -q` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/test_search_outcomes.py src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/test_search_outcomes.py src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/test_search_outcomes.py src/vaultspec_rag/server/_routes_search.py src/vaultspec_rag/_public_search.py src/vaultspec_rag/search/_outcomes.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
