---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:90a4f7533504f4985a0b252eed3229b43662db44e5ed4fa505511b93dec7b940'
step_id: 'S32'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Prove queued visibility deadlines bounded history completion and cancellation cleanup

## Scope

- `src/vaultspec_rag/tests/test_search_activity.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_search_activity.py`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/test_search_activity.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/test_search_activity.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/test_search_activity.py` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_search_activity.py src/vaultspec_rag/tests/test_http_search_routing.py src/vaultspec_rag/tests/test_server.py -q` -> `pass`
- `verify:` `git diff --check` -> `pass`
