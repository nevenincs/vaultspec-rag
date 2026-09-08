---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:241beba602ae7e81ff92880369376cf32a3aa434d142bd6557e6bbd6f5d0735b'
step_id: 'S08'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Implement a service-owned readiness revision registry and cancellable monotonic publication waiter

## Scope

- `src/vaultspec_rag/server/_search_readiness.py`

## Changes

- `A` `src/vaultspec_rag/server/_search_readiness.py`
- `M` `.vault/plan/2026-09-08-search-readiness-contract-plan.md`
- `M` `.vault/index/search-readiness-contract.index.md`
- `A` `.vault/exec/2026-09-08-search-readiness-contract/2026-09-08-search-readiness-contract-W01-P03-S08.md`
- `verify:` `uv run ruff format --check src/vaultspec_rag/server/_search_readiness.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/server/_search_readiness.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/server/_search_readiness.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_service_registry_recovery.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_server.py -k "DaemonLifecycleHelpers or ServiceRegistryIntegration"` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_service_quiesce_routes.py` -> `pass`
